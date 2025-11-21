#!/bin/bash

# 为 GRAID Web GUI 创建所有缺失的前端文件

set -e

PROJECT_DIR="${1:-.}"

echo "📦 Building..."

# 1. 前端 Dockerfile
cat > "$PROJECT_DIR/frontend/Dockerfile" << 'EOFRONTEND'
FROM node:18-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm install

COPY src ./src
COPY public ./public

RUN npm run build

FROM node:18-alpine

WORKDIR /app

RUN npm install -g serve

COPY --from=builder /app/build ./build

EXPOSE 3000

CMD ["serve", "-s", "build", "-l", "3000"]
EOFRONTEND

echo "✅ frontend/Dockerfile Complete"

# 2. 前端 index.js
cat > "$PROJECT_DIR/frontend/src/index.js" << 'EOJS'
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
EOJS

echo "✅ frontend/src/index.js already built"

# 3. 前端 App.jsx
cat > "$PROJECT_DIR/frontend/src/App.jsx" << 'EOREACT'
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_BASE_URL = 'http://localhost:5000';

function App() {
  const [activeTab, setActiveTab] = useState('config');
  const [config, setConfig] = useState({});
  const [benchmarkRunning, setBenchmarkRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [results, setResults] = useState([]);

  useEffect(() => {
    loadConfig();
    checkBenchmarkStatus();
    const interval = setInterval(checkBenchmarkStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadConfig = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/config`);
      if (response.data.success) {
        setConfig(response.data.data);
        setError('');
      }
    } catch (err) {
      setError('加载配置失败: ' + err.message);
    }
  };

  const checkBenchmarkStatus = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/benchmark/status`);
      if (response.data.success) {
        setBenchmarkRunning(response.data.data.running);
      }
    } catch (err) {
      console.error('Check status failed:', err);
    }
  };

  const handleStartTest = async () => {
    try {
      const response = await axios.post(`${API_BASE_URL}/api/benchmark/start`, { config });
      if (response.data.success) {
        setStatus('✅ Benchmark started');
        setBenchmarkRunning(true);
        setError('');
      }
    } catch (err) {
      setError('❌ Benchmark Start failed: ' + err.message);
    }
  };

  const handleStopTest = async () => {
    try {
      const response = await axios.post(`${API_BASE_URL}/api/benchmark/stop`);
      if (response.data.success) {
        setStatus('⏹️ 测试已停止');
        setBenchmarkRunning(false);
      }
    } catch (err) {
      setError('❌ Stop Benchmark failed: ' + err.message);
    }
  };

  const loadResults = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/results`);
      if (response.data.success) {
        setResults(response.data.data);
      }
    } catch (err) {
      setError('Loading results failed: ' + err.message);
    }
  };

  const handleConfigChange = (key, value) => {
    setConfig(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const saveConfig = async () => {
    try {
      const response = await axios.post(`${API_BASE_URL}/api/config`, config);
      if (response.data.success) {
        setStatus('✅ Config saved');
        setError('');
      }
    } catch (err) {
      setError('❌ Save config failed: ' + err.message);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>🚀 GRAID Benchmark Web GUI</h1>
        <div className="header-status">
          {benchmarkRunning ? (
            <span className="status-running">● Running</span>
          ) : (
            <span className="status-idle">● Done</span>
          )}
        </div>
      </header>

      {error && (
        <div className="error-banner">
          {error}
          <button onClick={() => setError('')}>Close</button>
        </div>
      )}
      {status && (
        <div className="status-banner">
          {status}
        </div>
      )}

      <div className="app-container">
        <div className="tabs">
          <button 
            className={`tab-button ${activeTab === 'config' ? 'active' : ''}`}
            onClick={() => setActiveTab('config')}
          >
            ⚙️ Config
          </button>
          <button 
            className={`tab-button ${activeTab === 'benchmark' ? 'active' : ''}`}
            onClick={() => setActiveTab('benchmark')}
          >
            ▶️ Run Benchmark
          </button>
          <button 
            className={`tab-button ${activeTab === 'results' ? 'active' : ''}`}
            onClick={() => {
              setActiveTab('results');
              loadResults();
            }}
          >
            💾 Result
          </button>
        </div>

        <div className="tab-content">
          {activeTab === 'config' && (
            <div className="config-panel">
              <h2>Config Management</h2>
              <div className="config-info">
                <p>Current Config:</p>
                <pre>{JSON.stringify(config, null, 2)}</pre>
              </div>
              <div className="config-actions">
                <button className="btn btn-primary" onClick={saveConfig}>
                  💾 Save
                </button>
                <button className="btn btn-secondary" onClick={loadConfig}>
                  🔄 Load old config
                </button>
              </div>
            </div>
          )}

          {activeTab === 'benchmark' && (
            <div className="benchmark-panel">
              <h2>Benchmark Control Board</h2>
              <div className="test-status">
                <div className="status-item">
                  <label>Running Status:</label>
                  <span className={benchmarkRunning ? 'running' : 'idle'}>
                    {benchmarkRunning ? '' : 'Not Running'}
                  </span>
                </div>
                <div className="status-item">
                  <label>Status:</label>
                  <span>{status || 'No Status'}</span>
                </div>
              </div>
              <div className="control-buttons">
                <button 
                  className="btn btn-success" 
                  onClick={handleStartTest}
                  disabled={benchmarkRunning}
                >
                  ▶️ Start Benchmark
                </button>
                <button 
                  className="btn btn-danger" 
                  onClick={handleStopTest}
                  disabled={!benchmarkRunning}
                >
                  ⏹️ Stop Benchmark
                </button>
              </div>
            </div>
          )}

          {activeTab === 'results' && (
            <div className="results-panel">
              <h2>Benchmark Results</h2>
              {results.length === 0 ? (
                <p className="empty-message">No results found</p>
              ) : (
                <div className="results-list">
                  {results.map((result, idx) => (
                    <div key={idx} className="result-item">
                      <h3>{result.name}</h3>
                      <p>Start Time: {result.created}</p>
                      <p>文件数: {result.files.length}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <footer className="app-footer">
        <p>Graid Benchmark Web GUI v1.0.0 | API: {API_BASE_URL}</p>
      </footer>
    </div>
  );
}

export default App;
EOREACT

echo "✅ frontend/src/App.jsx Successfully Created"

# 4. 前端 App.css
cat > "$PROJECT_DIR/frontend/src/App.css" << 'EOCSS'
:root {
  --primary-color: #3498db;
  --success-color: #27ae60;
  --danger-color: #e74c3c;
  --light-color: #ecf0f1;
  --text-color: #2c3e50;
  --bg-color: #f5f6fa;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #root {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  background-color: var(--bg-color);
  color: var(--text-color);
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  background: linear-gradient(135deg, var(--primary-color), #2980b9);
  color: white;
  padding: 2rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.app-header h1 {
  font-size: 1.8rem;
  font-weight: 600;
}

.header-status {
  font-size: 1rem;
  font-weight: 500;
}

.status-running {
  color: #2ecc71;
  animation: pulse 1s infinite;
}

.status-idle {
  color: #f39c12;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.error-banner {
  background-color: var(--danger-color);
  color: white;
  padding: 1rem 2rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.error-banner button {
  background: none;
  border: none;
  color: white;
  cursor: pointer;
  font-weight: bold;
}

.status-banner {
  background-color: var(--primary-color);
  color: white;
  padding: 1rem 2rem;
  text-align: center;
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from { transform: translateY(-100%); }
  to { transform: translateY(0); }
}

.app-container {
  flex: 1;
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 2rem;
  border-bottom: 2px solid var(--light-color);
  flex-wrap: wrap;
}

.tab-button {
  background: none;
  border: none;
  padding: 1rem 1.5rem;
  cursor: pointer;
  font-size: 1rem;
  color: var(--text-color);
  border-bottom: 3px solid transparent;
  transition: all 0.3s ease;
  font-weight: 500;
}

.tab-button:hover {
  color: var(--primary-color);
}

.tab-button.active {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
}

.tab-content {
  background: white;
  border-radius: 8px;
  padding: 2rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  animation: fadeIn 0.3s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.config-panel, .benchmark-panel, .results-panel {
  min-height: 300px;
}

.config-info {
  background-color: var(--bg-color);
  padding: 1rem;
  border-radius: 4px;
  margin: 1rem 0;
}

.config-info pre {
  background-color: white;
  padding: 1rem;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 0.9rem;
  border: 1px solid var(--light-color);
}

.config-actions, .control-buttons {
  display: flex;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}

.test-status {
  background-color: var(--bg-color);
  padding: 1rem;
  border-radius: 4px;
  margin: 1rem 0;
}

.status-item {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--light-color);
}

.status-item label {
  font-weight: 600;
  min-width: 100px;
}

.status-item .running {
  color: var(--success-color);
  font-weight: 600;
}

.status-item .idle {
  color: var(--text-color);
}

.btn {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 1rem;
  font-weight: 500;
  transition: all 0.3s ease;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background-color: var(--primary-color);
  color: white;
}

.btn-success {
  background-color: var(--success-color);
  color: white;
}

.btn-danger {
  background-color: var(--danger-color);
  color: white;
}

.btn-secondary {
  background-color: var(--light-color);
  color: var(--text-color);
  border: 1px solid var(--text-color);
}

.empty-message {
  text-align: center;
  padding: 3rem;
  color: var(--text-color);
  opacity: 0.7;
  font-style: italic;
}

.results-list {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
}

.result-item {
  background-color: var(--bg-color);
  padding: 1rem;
  border-radius: 4px;
  border: 1px solid var(--light-color);
}

.result-item h3 {
  margin-bottom: 0.5rem;
  color: var(--primary-color);
}

.result-item p {
  font-size: 0.9rem;
  margin-bottom: 0.25rem;
  opacity: 0.7;
}

.app-footer {
  text-align: center;
  padding: 1rem;
  border-top: 1px solid var(--light-color);
  background-color: white;
  margin-top: auto;
  font-size: 0.9rem;
  color: var(--text-color);
  opacity: 0.7;
}

@media (max-width: 768px) {
  .app-header {
    flex-direction: column;
    gap: 1rem;
  }

  .app-container {
    padding: 1rem;
  }

  .tabs {
    overflow-x: auto;
  }

  .tab-button {
    padding: 0.75rem 1rem;
    font-size: 0.9rem;
    white-space: nowrap;
  }

  .config-actions, .control-buttons {
    flex-direction: column;
  }

  .btn {
    width: 100%;
    justify-content: center;
  }
}
EOCSS

echo "✅ frontend/src/App.css Created"

# 5. 前端 public/index.html
cat > "$PROJECT_DIR/frontend/public/index.html" << 'EOHTMLEOF'
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#3498db" />
    <meta name="description" content="Graid Benchmark Web GUI" />
    <title>Graid Benchmark Web GUI</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
EOHTMLEOF

echo "✅ frontend/public/index.html 已创建"

# 6. 创建 .gitkeep 文件以保持目录结构
touch "$PROJECT_DIR/scripts/.gitkeep"
touch "$PROJECT_DIR/results/.gitkeep"
touch "$PROJECT_DIR/logs/.gitkeep"

echo ""
echo "=========================================="
echo "✅ All frontend files created!"
echo "=========================================="
echo ""
echo "📁 Forntend list:"
echo "frontend/"
echo "├── Dockerfile"
echo "├── public/"
echo "│   └── index.html"
echo "├── src/"
echo "│   ├── App.jsx"
echo "│   ├── App.css"
echo "│   └── index.js"
echo "└── package.json"
echo ""
echo "🚀 Now start:"
echo "   sudo docker-compose up -d"
echo ""