import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_BASE_URL = 'http://localhost:50071';

const HIDDEN_PARAMS = [
  'storcli_command',
  'benchtask_name',
  'RUN_MR',
  'MR_NAME',
  'EID',
  'SID',
  'WP_LS',
  'RUN_MD',
];

const validateConfig = (cfg) => {
  const errors = [];

  // 处理可能是字符串或数组的情况
  let nvmeList = cfg.NVME_LIST;
  if (typeof nvmeList === 'string') {
    nvmeList = nvmeList.split(',').map(s => s.trim()).filter(s => s);
  }
  const nvmeCount = (nvmeList || []).length;

  let raidTypes = cfg.RAID_TYPE;
  if (typeof raidTypes === 'string') {
    raidTypes = raidTypes.split(',').map(s => s.trim()).filter(s => s);
  }
  raidTypes = raidTypes || [];
  if (raidTypes.includes('RAID5') && nvmeCount < 3) {
    errors.push('⚠️ RAID5 requires at least 3 NVMe devices...');
  }

  if (raidTypes.includes('RAID6') && nvmeCount < 4) {
    errors.push('⚠️ RAID6 requires at least 4 NVMe devices...');
  }
  // 检查 RAID1/RAID10 需要偶数设备
  if (raidTypes.includes('RAID1') || raidTypes.includes('RAID10')) {
    if (nvmeCount % 2 !== 0) {
      errors.push(
        `⚠️ RAID1 and RAID10 require an even number of NVMe devices. ` +
        `Current: ${nvmeCount} devices. Please add or remove one device.`
      );
    }
  }

  // 检查是否至少有一个设备
  if (nvmeCount === 0) {
    errors.push('⚠️ At least one NVMe device is required.');
  }

  // 检查 RAID 类型是否有效
  const validRaidTypes = ['RAID0', 'RAID1', 'RAID5', 'RAID6', 'RAID10'];
  const invalidRaids = raidTypes.filter(r => !validRaidTypes.includes(r));
  if (invalidRaids.length > 0) {
    errors.push(`⚠️ Invalid RAID types: ${invalidRaids.join(', ')}`);
  }

  // 检查运行时间是否合理
  if (cfg.PD_RUNTIME < 10 || cfg.VD_RUNTIME < 10) {
    errors.push('⚠️ Runtime should be at least 10 seconds.');
  }

  return errors;
};

function App() {
  const [activeTab, setActiveTab] = useState('config');
  const [config, setConfig] = useState({});
  const [benchmarkRunning, setBenchmarkRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [validationErrors, setValidationErrors] = useState([]); // ✅ 添加这个状态
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
      setError('Loading config failed: ' + err.message);
    }
  };

  const checkBenchmarkStatus = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/benchmark/status`);
      if (response.data.success) {
        setBenchmarkRunning(response.data.data.running);
      }
    } catch (err) {
      console.error('Checking benchmark status failed:', err);
    }
  };

  // ✅ 添加这个辅助函数
  const processArrayFields = (cfg) => {
    const processed = { ...cfg };
    const arrayFields = ['NVME_LIST', 'RAID_TYPE', 'TS_LS', 'STA_LS', 'JOB_LS', 'QD_LS', 'BS_LS', 'pd_jobs', 'WP_LS'];

    arrayFields.forEach(key => {
      if (typeof processed[key] === 'string') {
        processed[key] = processed[key].split(',').map(s => s.trim()).filter(s => s);
      }
    });

    return processed;
  };

  const handleStartTest = async () => {
    // 启动前先转换所有数组字段
    const processedConfig = processArrayFields(config);

    // 验证处理后的配置
    const errors = validateConfig(processedConfig);
    setValidationErrors(errors);

    if (errors.length > 0) {
      setError('❌ Configuration validation failed. Please fix the errors below.');
      return;
    }

    try {
      const response = await axios.post(`${API_BASE_URL}/api/benchmark/start`, {
        config: processedConfig
      });
      if (response.data.success) {
        setStatus('✅ Benchmark started');
        setBenchmarkRunning(true);
        setError('');
        setValidationErrors([]);
      }
    } catch (err) {
      setError('❌ Starting benchmark failed: ' + err.message);
    }
  };

  const handleStopTest = async () => {
    try {
      const response = await axios.post(`${API_BASE_URL}/api/benchmark/stop`);
      if (response.data.success) {
        setStatus('⏹️ Benchmark stopped');
        setBenchmarkRunning(false);
      }
    } catch (err) {
      setError('❌ Stopping benchmark failed: ' + err.message);
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
    setValidationErrors([]); // 清除验证错误
  };

  const handleArrayChange = (key, value) => {
    setConfig(prev => ({ ...prev, [key]: value }));
    setValidationErrors([]);
  };

  const handleArrayBlur = (key, value) => {
    const array = value.split(',').map(s => s.trim()).filter(s => s);
    setConfig(prev => ({ ...prev, [key]: array }));
  };

  const getArrayDisplayValue = (value) => {
    return Array.isArray(value) ? value.join(', ') : (value || '');
  };

  const saveConfig = async () => {
    // 转换字符串为数组
    const processed = processArrayFields(config);

    const errors = validateConfig(processed);
    if (errors.length > 0) {
      setValidationErrors(errors);
      setError('❌ Configuration has errors. Please fix them before saving.');
      return;
    }

    try {
      const response = await axios.post(`${API_BASE_URL}/api/config`, processed);
      if (response.data.success) {
        setConfig(processed);
        setStatus('✅ Config saved successfully');
        setError('');
        setValidationErrors([]);
        setTimeout(() => setStatus(''), 3000);
      }
    } catch (err) {
      setError('❌ Failed to save config: ' + err.message);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>🚀 SupremeRAID Benchmark Web GUI</h1>
        <div className="header-status">
          {benchmarkRunning ? (
            <span className="status-running">● Running</span>
          ) : (
            <span className="status-idle">● Standby</span>
          )}
        </div>
      </header>

      {error && (
        <div className="error-banner">
          {error}
          <button onClick={() => setError('')}>Close</button>
        </div>
      )}

      {/* ✅ 添加验证错误显示 */}
      {validationErrors.length > 0 && (
        <div className="validation-errors">
          <h4>⚠️ Validation Errors:</h4>
          <ul>
            {validationErrors.map((err, idx) => (
              <li key={idx}>{err}</li>
            ))}
          </ul>
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
            ⚙️ Config management
          </button>
          <button
            className={`tab-button ${activeTab === 'benchmark' ? 'active' : ''}`}
            onClick={() => setActiveTab('benchmark')}
          >
            ▶️ Benchmark
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
              <h2>Configuration Editor</h2>

              <div className="config-form">
                {/* 基本信息 */}
                <div className="config-section">
                  <h3>📋 Basic Information</h3>

                  <div className="form-group">
                    <label>NVMe Device Info:</label>
                    <input
                      type="text"
                      value={config.NVME_INFO || ''}
                      onChange={(e) => handleConfigChange('NVME_INFO', e.target.value)}
                      placeholder="Samsung-PM1733"
                    />
                  </div>

                  <div className="form-group">
                    <label>
                      NVMe Device List (comma separated):
                      <span className="hint"> Currently: {
                        (() => {
                          const value = config.NVME_LIST;
                          if (Array.isArray(value)) return value.length;
                          if (typeof value === 'string') {
                            return value.split(',').map(s => s.trim()).filter(s => s).length;
                          }
                          return 0;
                        })()
                      } device(s)</span>
                    </label>
                    <input
                      type="text"
                      value={getArrayDisplayValue(config.NVME_LIST)}
                      onChange={(e) => handleArrayChange('NVME_LIST', e.target.value)}
                      onBlur={(e) => handleArrayBlur('NVME_LIST', e.target.value)}
                      placeholder="nvme0n1, nvme1n1, nvme2n1, nvme3n1"
                    />
                    {/* 实时验证提示 */}
                    {(() => {
                      const value = config.NVME_LIST;
                      let count;
                      if (Array.isArray(value)) {
                        count = value.length;
                      } else if (typeof value === 'string') {
                        count = value.split(',').map(s => s.trim()).filter(s => s).length;
                      } else {
                        count = 0;
                      }

                      const raidTypes = Array.isArray(config.RAID_TYPE)
                        ? config.RAID_TYPE
                        : (typeof config.RAID_TYPE === 'string'
                          ? config.RAID_TYPE.split(',').map(s => s.trim()).filter(s => s)
                          : []);

                      const warnings = [];

                      if (count % 2 !== 0 && raidTypes.some(r => r === 'RAID1' || r === 'RAID10')) {
                        warnings.push(`RAID1/RAID10 require even number of devices (current: ${count})`);
                      }
                      if (count < 3 && raidTypes.includes('RAID5')) {
                        warnings.push(`RAID5 requires at least 3 devices (current: ${count}, need ${3 - count} more)`);
                      }

                      if (count < 4 && raidTypes.includes('RAID6')) {
                        warnings.push(`RAID6 requires at least 4 devices (current: ${count}, need ${4 - count} more)`);
                      }

                      if (warnings.length > 0) {
                        return (
                          <div className="field-warning">
                            ⚠️ {warnings.join(' | ')}
                          </div>
                        );
                      }

                      return null;
                    })()}
                  </div>

                  <div className="form-group">
                    <label>RAID Controller:</label>
                    <input
                      type="text"
                      value={config.RAID_CTRLR || ''}
                      onChange={(e) => handleConfigChange('RAID_CTRLR', e.target.value)}
                      placeholder="SR1000"
                    />
                  </div>

                  <div className="form-group">
                    <label>VD Name:</label>
                    <input
                      type="text"
                      value={config.VD_NAME || ''}
                      onChange={(e) => handleConfigChange('VD_NAME', e.target.value)}
                      placeholder="gdg0n1"
                    />
                    <span className="hint">For GRAID v1.3.x use "gdg0n1", v1.2.x use "gvd0n1"</span>
                  </div>
                </div>

                {/* RAID 配置 */}
                <div className="config-section">
                  <h3>🔧 RAID Configuration</h3>

                  <div className="form-group">
                    <label>RAID Types (comma separated):</label>
                    <input
                      type="text"
                      value={getArrayDisplayValue(config.RAID_TYPE)}
                      onChange={(e) => handleArrayChange('RAID_TYPE', e.target.value)}
                      onBlur={(e) => handleArrayBlur('RAID_TYPE', e.target.value)}
                      placeholder="RAID5, RAID6, RAID10"
                    />
                    <span className="hint">Valid: RAID0, RAID1, RAID5, RAID6, RAID10</span>
                  </div>
                </div>

                {/* 测试配置 */}
                <div className="config-section">
                  <h3>🧪 Test Configuration</h3>

                  <div className="form-group">
                    <label>Test Stages (comma separated):</label>
                    <input
                      type="text"
                      value={getArrayDisplayValue(config.TS_LS)}
                      onChange={(e) => handleArrayChange('TS_LS', e.target.value)}
                      onBlur={(e) => handleArrayBlur('TS_LS', e.target.value)}
                      placeholder="afterdiscard, afterprecondition"
                    />
                    <span className="hint">Options: afterdiscard, afterprecondition, aftersustain</span>
                  </div>

                  <div className="form-group">
                    <label>Status List (comma separated):</label>
                    <input
                      type="text"
                      value={getArrayDisplayValue(config.STA_LS)}
                      onChange={(e) => handleArrayChange('STA_LS', e.target.value)}
                      onBlur={(e) => handleArrayBlur('STA_LS', e.target.value)}
                      placeholder="Normal"
                    />
                    <span className="hint">Options: Normal, Rebuild</span>
                  </div>

                  <div className="form-group">
                    <label>Queue Depth List (comma separated):</label>
                    <input
                      type="text"
                      value={getArrayDisplayValue(config.QD_LS)}
                      onChange={(e) => handleArrayChange('QD_LS', e.target.value)}
                      onBlur={(e) => handleArrayBlur('QD_LS', e.target.value)}
                      placeholder="64"
                    />
                  </div>

                  <div className="form-group">
                    <label>PD Jobs (comma separated):</label>
                    <input
                      type="text"
                      value={getArrayDisplayValue(config.pd_jobs)}
                      onChange={(e) => handleArrayChange('pd_jobs', e.target.value)}
                      onBlur={(e) => handleArrayBlur('pd_jobs', e.target.value)}
                      placeholder="8"
                    />
                  </div>
                </div>

                {/* 运行时间 */}
                <div className="config-section">
                  <h3>⏱️ Runtime Configuration</h3>

                  <div className="form-group">
                    <label>Physical Drive Test Runtime (seconds):</label>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        value={config.PD_RUNTIME || 180}
                        onChange={(e) => handleConfigChange('PD_RUNTIME', parseInt(e.target.value))}
                        min="10"
                        step="10"
                      />
                      <span className="unit">seconds</span>
                    </div>
                    <span className="hint">Minimum: 10 seconds (180s = 3 minutes recommended)</span>
                  </div>

                  <div className="form-group">
                    <label>Virtual Drive Test Runtime (seconds):</label>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        value={config.VD_RUNTIME || 180}
                        onChange={(e) => handleConfigChange('VD_RUNTIME', parseInt(e.target.value))}
                        min="10"
                        step="10"
                      />
                      <span className="unit">seconds</span>
                    </div>
                    <span className="hint">Minimum: 10 seconds (180s = 3 minutes recommended)</span>
                  </div>
                </div>

                {/* 测试开关 */}
                <div className="config-section">
                  <h3>🔘 Test Switches</h3>

                  <div className="form-group checkbox-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={config.QUICK_TEST || false}
                        onChange={(e) => handleConfigChange('QUICK_TEST', e.target.checked)}
                      />
                      Quick Test Mode
                    </label>
                  </div>

                  <div className="form-group checkbox-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={config.LOG_COMPACT || false}
                        onChange={(e) => handleConfigChange('LOG_COMPACT', e.target.checked)}
                      />
                      Compact Log
                    </label>
                  </div>

                  <div className="form-group checkbox-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={config.SCAN || false}
                        onChange={(e) => handleConfigChange('SCAN', e.target.checked)}
                      />
                      Full Scan
                    </label>
                  </div>

                  <div className="form-group checkbox-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={config.RUN_PD || false}
                        onChange={(e) => handleConfigChange('RUN_PD', e.target.checked)}
                      />
                      Run Physical Drive Test
                    </label>
                  </div>

                  <div className="form-group checkbox-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={config.RUN_VD || false}
                        onChange={(e) => handleConfigChange('RUN_VD', e.target.checked)}
                      />
                      Run Virtual Drive Test
                    </label>
                  </div>

                  <div className="form-group checkbox-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={config.RUN_PD_ALL || false}
                        onChange={(e) => handleConfigChange('RUN_PD_ALL', e.target.checked)}
                      />
                      Test All Physical Drives
                    </label>
                  </div>
                </div>
              </div>

              <div className="config-actions">
                <button className="btn btn-primary" onClick={saveConfig}>
                  💾 Save Configuration
                </button>
                <button className="btn btn-secondary" onClick={loadConfig}>
                  🔄 Reload Configuration
                </button>
              </div>

              {/* 显示原始 JSON（可折叠），排除隐藏参数 */}
              <details className="config-raw">
                <summary>📄 View Raw JSON (Visible Parameters Only)</summary>
                <pre>{JSON.stringify(
                  Object.fromEntries(
                    Object.entries(config).filter(([key]) => !HIDDEN_PARAMS.includes(key))
                  ),
                  null,
                  2
                )}</pre>
              </details>
            </div>
          )}

          {activeTab === 'benchmark' && (
            <div className="benchmark-panel">
              <h2>Benchmarking Control Board</h2>

              {validationErrors.length > 0 && (
                <div className="validation-errors">
                  <h4>⚠️ Please fix configuration errors before starting:</h4>
                  <ul>
                    {validationErrors.map((err, idx) => (
                      <li key={idx}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="test-status">
                <div className="status-item">
                  <label>Running Status:</label>
                  <span className={benchmarkRunning ? 'running' : 'idle'}>
                    {benchmarkRunning ? 'Benchmarking' : 'Not Running'}
                  </span>
                </div>
                <div className="status-item">
                  <label>Final Status:</label>
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
              <h2>Test Results</h2>
              {results.length === 0 ? (
                <p className="empty-message">No results found</p>
              ) : (
                <div className="results-list">
                  {results.map((result, idx) => (
                    <div key={idx} className="result-item">
                      <h3>{result.name}</h3>
                      <p>Testing Time: {result.created}</p>
                      <p>Files: {result.files.length}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <footer className="app-footer">
        <p>SupremeRAID Benchmark Web GUI v1.0.0 | API: {API_BASE_URL}</p>
      </footer>
    </div>
  );
}

export default App;