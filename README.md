# MilashkaAI Assistant

A browser extension and server implementation for AI-powered text assistance with voice input support and RAG-enhanced context awareness.

## Features

### Text Assistance
- Smart text completion with contextual awareness
- Real-time suggestions as you type
- Support for multiple languages (Russian and English)
- Ghost text display with Tab/Enter to accept, Esc to reject

### Text Editing
- Context-menu and selection-based text editing
- Voice command support for edits
- Multiple edit alternatives with confidence scoring
- Preview functionality before applying changes

### Document Processing
- Support for PDF, DOCX, TXT, and Markdown files
- Background processing with status tracking
- RAG-based context retrieval for better suggestions
- Efficient vector search and similarity matching

### Voice Input
- Real-time voice transcription
- Automatic formatting and punctuation
- Structured requirement extraction
- WebSocket streaming for low-latency feedback

## Installation

### Server Setup
1. Install Python requirements:
```bash
cd server
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your settings
```

3. Start the server:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Browser Extension Setup
1. Load the extension in Chrome/Firefox:
   - Chrome: Open chrome://extensions/
   - Enable Developer Mode
   - Click "Load unpacked" and select the extension folder

2. Configure the extension:
   - Click the extension icon
   - Go to options
   - Set the API endpoint URL

## Usage

### Text Completion
1. Start typing in any text input field
2. Ghost text suggestions will appear automatically
3. Press Tab or Enter to accept, Esc to reject

### Text Editing
1. Select text you want to edit
2. Either:
   - Right-click and select "Edit with MilashkaAI"
   - Use the floating edit menu that appears
3. Enter your edit request or use voice input
4. Review and apply the changes

### Document Upload
1. Click the extension icon
2. Drag & drop files or click to select
3. Monitor upload and processing status
4. Once indexed, documents provide context for completions

### Voice Input
1. Click the microphone icon
2. Speak your command or text
3. Review the transcription
4. Accept or modify the result

## API Documentation

The server provides a comprehensive API:

### Base URL: `/api/v1`

#### Document Endpoints
- `POST /documents/upload` - Upload new document
- `GET /documents` - List all documents
- `GET /documents/{doc_id}` - Get document status
- `DELETE /documents/{doc_id}` - Delete document

#### Completion Endpoints
- `POST /completion` - Get text completion
- `POST /completion/stream` - Stream completions

#### Voice Endpoints
- `POST /voice/transcribe` - Transcribe audio file
- `WebSocket /voice/stream-transcribe` - Stream transcription
- `POST /voice/to-requirement` - Extract structured requirements

#### Editing Endpoints
- `POST /editing` - Edit text based on prompt
- `POST /editing/preview` - Preview multiple alternatives
- `POST /editing/evaluate` - Evaluate edit quality

#### RAG Endpoints
- `GET /rag/search` - Search through indexed documents
- `POST /rag/reindex/{doc_id}` - Reindex specific document
- `GET /rag/similar` - Find similar text chunks

## Security

- API key authentication
- Rate limiting per endpoint
- CORS and trusted host validation
- Security headers
- Input validation and sanitization

## Performance

- Efficient task queue for background processing
- Caching support for frequent operations
- Batch processing for document indexing
- Streaming support for real-time operations

## Error Handling

- Comprehensive error responses
- Automatic retries for transient failures
- Graceful degradation when services are unavailable
- Detailed logging for troubleshooting

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.