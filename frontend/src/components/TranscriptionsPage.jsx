import React, { useState, useEffect } from 'react'
import { Container, Row, Col, Card, Button, Alert, Spinner, ListGroup } from 'react-bootstrap'
import { FiDownload, FiFileText, FiRefreshCw } from 'react-icons/fi'
import axios from 'axios'

const TranscriptionsPage = () => {
  const [transcriptions, setTranscriptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchTranscriptions = async () => {
    try {
      setLoading(true)
      const response = await axios.get('/api/v1/transcription/files/')
      setTranscriptions(response.data)
      setError('')
    } catch (err) {
      setError('Erro ao carregar transcrições: ' + (err.response?.data?.detail || err.message))
    } finally {
      setLoading(false)
    }
  }

  const downloadFile = (filename) => {
    window.open(`/output/${filename}`, '_blank')
  }

  useEffect(() => {
    fetchTranscriptions()
  }, [])

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const formatDate = (timestamp) => {
    return new Date(timestamp * 1000).toLocaleString('pt-BR')
  }

  return (
    <Container>
      <Row className="justify-content-md-center">
        <Col md={10}>
          <div className="d-flex justify-content-between align-items-center mb-4">
            <h2>📝 Transcrições Disponíveis</h2>
            <Button 
              variant="outline-primary" 
              onClick={fetchTranscriptions}
              disabled={loading}
            >
              <FiRefreshCw className={`me-2 ${loading ? 'spin' : ''}`} />
              Atualizar
            </Button>
          </div>

          {error && (
            <Alert variant="danger" onClose={() => setError('')} dismissible>
              {error}
            </Alert>
          )}

          {loading ? (
            <div className="text-center">
              <Spinner animation="border" variant="primary" />
              <p className="mt-2">Carregando transcrições...</p>
            </div>
          ) : transcriptions.length === 0 ? (
            <Card>
              <Card.Body className="text-center">
                <FiFileText size={48} className="text-muted mb-3" />
                <h4>Nenhuma transcrição disponível</h4>
                <p className="text-muted">
                  Faça upload de arquivos de áudio para gerar transcrições.
                </p>
              </Card.Body>
            </Card>
          ) : (
            <Card>
              <Card.Body>
                <ListGroup variant="flush">
                  {transcriptions.map((file, index) => (
                    <ListGroup.Item key={index} className="d-flex justify-content-between align-items-center">
                      <div>
                        <h6 className="mb-1">
                          <FiFileText className="me-2 text-primary" />
                          {file.filename}
                        </h6>
                        <small className="text-muted">
                          Tamanho: {formatFileSize(file.size)} | 
                          Modificado: {formatDate(file.modified)}
                        </small>
                      </div>
                      <Button 
                        variant="outline-success" 
                        size="sm"
                        onClick={() => downloadFile(file.filename)}
                      >
                        <FiDownload className="me-1" />
                        Download
                      </Button>
                    </ListGroup.Item>
                  ))}
                </ListGroup>
              </Card.Body>
            </Card>
          )}
        </Col>
      </Row>
    </Container>
  )
}

export default TranscriptionsPage