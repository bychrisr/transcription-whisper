import React from 'react'
import { Container, Navbar, Nav } from 'react-bootstrap'
import { Routes, Route, Link, BrowserRouter } from 'react-router-dom'
import UploadPage from './pages/UploadPage'
import TranscriptionsPage from './pages/TranscriptionsPage'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <div className="App">
        <Navbar bg="dark" variant="dark" expand="lg">
          <Container>
            <Navbar.Brand as={Link} to="/">🎙️ Whisper Transcription</Navbar.Brand>
            <Nav className="me-auto">
              <Nav.Link as={Link} to="/">Upload</Nav.Link>
              <Nav.Link as={Link} to="/transcriptions">Transcrições</Nav.Link>
            </Nav>
          </Container>
        </Navbar>

        <Container className="mt-4">
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/transcriptions" element={<TranscriptionsPage />} />
          </Routes>
        </Container>
      </div>
    </BrowserRouter>
  )
}

export default App