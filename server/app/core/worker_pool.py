"""
Process pool manager for handling LLM completion requests efficiently.
Pre-warms processes to avoid the delay of model loading on each request.
"""
import os
import time
import logging
import multiprocessing
from multiprocessing import Process, Queue
from typing import Dict, List, Any, Optional, Tuple, Callable
import queue
import atexit

# Set tokenizers parallelism environment variable
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Worker states
WORKER_IDLE = "idle"
WORKER_BUSY = "busy"
WORKER_STARTING = "starting"
WORKER_ERROR = "error"
WORKER_DEAD = "dead"

class WorkerProcess:
    """Represents a worker process in the pool"""
    def __init__(self, process_id: int, process: Process, request_queue: Queue, response_queue: Queue):
        self.id = process_id
        self.process = process
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.state = WORKER_STARTING
        self.current_job_id: Optional[str] = None
        self.started_at = time.time()
        self.last_used = time.time()
        self.error_count = 0

class WorkerPoolManager:
    """Manages a pool of pre-warmed worker processes for LLM inference"""
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = WorkerPoolManager()
        return cls._instance
    
    def __init__(self):
        """Initialize the worker pool manager"""
        # Config
        self.min_workers = 2  # Minimum number of workers to keep ready
        self.max_workers = 4  # Maximum number of workers to create
        self.worker_timeout = 300  # Consider a worker dead if no response for 5 minutes
        self.worker_max_jobs = 10  # Restart worker after this many jobs
        self.worker_init_timeout = 60  # Wait up to 60s for worker to initialize
        
        # State
        self.next_worker_id = 1
        self.workers: Dict[int, WorkerProcess] = {}
        self.job_to_worker: Dict[str, int] = {}
        self.next_job_id = 1
        self.initialized = False
        self.maintenance_job = None
        self.workers_ready = False
        
        # Register cleanup function
        atexit.register(self.shutdown)
        
    def initialize(self, worker_target: Callable):
        """Initialize the worker pool with the specified worker function"""
        self.worker_target = worker_target
        self.initialized = True
        
        # Start initial workers
        for _ in range(self.min_workers):
            self._create_worker()
        
        # Wait for at least one worker to be ready
        logging.info(f"Waiting for at least one worker to be ready...")
        start_time = time.time()
        while not self._get_idle_worker_count() > 0:
            time.sleep(0.1)
            # Check for timeout
            if time.time() - start_time > self.worker_init_timeout:
                logging.warning("Timed out waiting for workers to initialize")
                break
            
        self.workers_ready = True
        logging.info(f"Worker pool initialized with {self._get_idle_worker_count()} ready workers")
        
    def _create_worker(self) -> int:
        """Create a new worker process and return its ID"""
        worker_id = self.next_worker_id
        self.next_worker_id += 1
        
        request_queue = Queue()
        response_queue = Queue()
        
        logging.info(f"Creating worker {worker_id}...")
        
        process = Process(
            target=self.worker_target,
            args=(worker_id, request_queue, response_queue),
            daemon=True
        )
        process.start()
        
        worker = WorkerProcess(
            process_id=worker_id,
            process=process,
            request_queue=request_queue,
            response_queue=response_queue
        )
        
        self.workers[worker_id] = worker
        return worker_id
        
    def request_worker(self, job_data: Dict) -> Tuple[str, Queue]:
        """
        Request a worker for a job. Returns a job ID and response queue.
        """
        if not self.initialized or not self.workers_ready:
            raise RuntimeError("Worker pool not initialized or not ready")
        
        # Get an idle worker or create a new one if needed
        worker = self._get_idle_worker()
        if worker is None:
            # If we're at max capacity, wait for an idle worker
            if len(self.workers) >= self.max_workers:
                logging.warning(f"All {len(self.workers)} workers busy, waiting for one to become available")
                # Try to clean up any dead workers first
                self._check_worker_health()
                # If still at capacity, wait for an idle worker
                if len(self.workers) >= self.max_workers:
                    worker = self._wait_for_idle_worker()
            
            # If we can create a new worker, do so
            if worker is None:
                worker_id = self._create_worker()
                # Wait for this worker to be ready
                start_time = time.time()
                while time.time() - start_time < self.worker_init_timeout:
                    worker = self.workers.get(worker_id)
                    if worker and worker.state == WORKER_IDLE:
                        break
                    time.sleep(0.1)
                else:
                    logging.warning(f"New worker {worker_id} did not become ready in time")
                    
                if worker_id in self.workers:
                    worker = self.workers[worker_id]
                else:
                    raise RuntimeError("Failed to create new worker")
        
        # Assign the job
        job_id = f"job_{self.next_job_id}"
        self.next_job_id += 1
        
        worker.state = WORKER_BUSY
        worker.current_job_id = job_id
        worker.last_used = time.time()
        self.job_to_worker[job_id] = worker.id
        
        # Send job to worker
        job_data["job_id"] = job_id
        worker.request_queue.put(job_data)
        
        return job_id, worker.response_queue
    
    def mark_job_done(self, job_id: str):
        """Mark a job as completed and worker as idle"""
        if job_id in self.job_to_worker:
            worker_id = self.job_to_worker[job_id]
            if worker_id in self.workers:
                worker = self.workers[worker_id]
                worker.state = WORKER_IDLE
                worker.current_job_id = None
                worker.last_used = time.time()
            del self.job_to_worker[job_id]
            
    def _get_idle_worker(self) -> Optional[WorkerProcess]:
        """Get an idle worker if available"""
        for worker in self.workers.values():
            if worker.state == WORKER_IDLE:
                return worker
        return None
    
    def _get_idle_worker_count(self) -> int:
        """Count how many workers are idle"""
        return sum(1 for w in self.workers.values() if w.state == WORKER_IDLE)
    
    def _wait_for_idle_worker(self, timeout=30) -> Optional[WorkerProcess]:
        """Wait for a worker to become idle, with timeout"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            worker = self._get_idle_worker()
            if worker:
                return worker
            time.sleep(0.1)
        return None
    
    def _check_worker_health(self):
        """Check workers' health and restart any that appear dead"""
        current_time = time.time()
        workers_to_remove = []
        
        for worker_id, worker in self.workers.items():
            # Check if process is still alive
            if not worker.process.is_alive():
                logging.warning(f"Worker {worker_id} process died")
                workers_to_remove.append(worker_id)
            
            # Check if worker has been busy for too long
            elif worker.state == WORKER_BUSY and (current_time - worker.last_used > self.worker_timeout):
                logging.warning(f"Worker {worker_id} appears stuck on job {worker.current_job_id}")
                try:
                    worker.process.terminate()
                except:
                    pass
                workers_to_remove.append(worker_id)
        
        # Remove dead workers
        for worker_id in workers_to_remove:
            if worker_id in self.workers:
                worker = self.workers[worker_id]
                if worker.current_job_id and worker.current_job_id in self.job_to_worker:
                    del self.job_to_worker[worker.current_job_id]
                del self.workers[worker_id]
        
        # Ensure minimum number of workers
        while self._get_idle_worker_count() < self.min_workers and len(self.workers) < self.max_workers:
            self._create_worker()
    
    def shutdown(self):
        """Shut down all worker processes"""
        logging.info("Shutting down worker pool...")
        for worker_id, worker in list(self.workers.items()):
            try:
                if worker.process.is_alive():
                    worker.process.terminate()
                    worker.process.join(timeout=1.0)
            except Exception as e:
                logging.error(f"Error terminating worker {worker_id}: {e}")
