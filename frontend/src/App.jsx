import React from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import UploadPage from './pages/UploadPage'
import TranscriptionsPage from './components/TranscriptionsPage'
import './index.css'

function App() {
  return (
    <Router>
      <div className="App">
        <header className="App-header">
          <h1>Whisper Transcription</h1>
        </header>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/transcriptions" element={<TranscriptionsPage />} />
        </Routes>
      </div>
    </Router>
  )
}

export default App