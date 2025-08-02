import React, { useState } from 'react'
import { Container, Row, Col, Card, Form, Button, Alert, ProgressBar } from 'react-bootstrap'
import { useDropzone } from 'react-dropzone'
import { FiUpload, FiFile, FiCheckCircle } from 'react-icons/fi'
import axios from 'axios'

const UploadPage = () => {
  const [files, setFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadResults, setUploadResults] = useState([])
  const [error, setError] = useState('')

  const onDrop = (acceptedFiles) => {
    setFiles(acceptedFiles.map(file => Object.assign(file, {
      preview: URL.createObjectURL(file)
    })))
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'audio/*': ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac']
    },
    maxFiles: 10
  })

  const handleUpload = async () => {
    if (files.length === 0) {
      setError('Por favor, selecione pelo menos um arquivo')
      return
    }

    setUploading(true)
    setError('')
    setUploadResults([])

    try {
      const results = []
      
      for (const file of files) {
        const formData = new FormData()
        formData.append('file', file)
        
        try {
          const response = await axios.post('/api/v1/transcription/upload/', formData, {
            headers: {
              'Content-Type': 'multipart/form-data'
            }
          })
          
          results.push({
            filename: file.name,
            status: 'success',
            taskId: response.data.task_id,
            message: response.data.message
          })
        } catch (err) {
          results.push({
            filename: file.name,
            status: 'error',
            message: err.response?.data?.detail || 'Erro no upload'
          })
        }
      }
      
      setUploadResults(results)
    } catch (err) {
      setError('Erro ao processar uploads: ' + err.message)
    } finally {
      setUploading(false)
      setFiles([])
    }
  }

  const removeFile = (fileName) => {
    setFiles(files.filter(file => file.name !== fileName))
  }

  return (
    <Container>
      <Row className="justify-content-md-center">
        <Col md={8}>
          <Card>
            <Card.Header className="bg-primary text-white">
              <h4 className="mb-0">📤 Upload de Áudios para Transcrição</h4>
            </Card.Header>
            <Card.Body>
              {error && (
                <Alert variant="danger" onClose={() => setError('')} dismissible>
                  {error}
                </Alert>
              )}

              <div {...getRootProps()} className={`dropzone ${isDragActive ? 'active' : ''}`}>
                <input {...getInputProps()} />
                <div className="text-center p-5">
                  <FiUpload size={48} className="text-muted mb-3" />
                  <p className="mb-2">
                    <strong>Arraste e solte arquivos de áudio aqui</strong>
                  </p>
                  <p className="text-muted">
                    Ou clique para selecionar arquivos (MP3, WAV, M4A, FLAC, OGG, AAC)
                  </p>
                </div>
              </div>

              {files.length > 0 && (
                <div className="mt-4">
                  <h6>Arquivos selecionados:</h6>
                  {files.map((file, index) => (
                    <div key={index} className="d-flex align-items-center justify-content-between border rounded p-2 mb-2">
                      <div className="d-flex align-items-center">
                        <FiFile className="me-2 text-primary" />
                        <span>{file.name}</span>
                      </div>
                      <Button 
                        variant="outline-danger" 
                        size="sm" 
                        onClick={() => removeFile(file.name)}
                      >
                        Remover
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              {uploadResults.length > 0 && (
                <div className="mt-4">
                  <h6>Resultados do Upload:</h6>
                  {uploadResults.map((result, index) => (
                    <Alert 
                      key={index} 
                      variant={result.status === 'success' ? 'success' : 'danger'}
                      className="d-flex align-items-center"
                    >
                      {result.status === 'success' ? (
                        <FiCheckCircle className="me-2" />
                      ) : (
                        <span className="me-2">❌</span>
                      )}
                      <div>
                        <strong>{result.filename}</strong>
                        <div className="small">{result.message}</div>
                        {result.taskId && (
                          <div className="small text-muted">Task ID: {result.taskId}</div>
                        )}
                      </div>
                    </Alert>
                  ))}
                </div>
              )}

              <div className="d-grid gap-2 mt-4">
                <Button 
                  variant="primary" 
                  size="lg" 
                  onClick={handleUpload}
                  disabled={uploading || files.length === 0}
                >
                  {uploading ? (
                    <>
                      <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                      Processando...
                    </>
                  ) : (
                    '📤 Enviar para Transcrição'
                  )}
                </Button>
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </Container>
  )
}

export default UploadPage