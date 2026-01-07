import React, { useState, useEffect } from 'react';
import axios from 'axios';
import html2canvas from 'html2canvas';
import './App.css';
import io from 'socket.io-client';
import RealTimeDashboard from './components/RealTimeDashboard';
import ComparisonDashboard from './components/ComparisonDashboard';

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
    errors.push('⚠️ RAID5 requires at least 3 NVMe devices.');
  }
  if (raidTypes.includes('RAID6') && nvmeCount < 4) {
    errors.push('⚠️ RAID6 requires at least 4 NVMe devices.');
  }
  if (raidTypes.includes('RAID1') && nvmeCount < 2) {
    errors.push('⚠️ RAID1 requires at least 2 NVMe devices.');
  }
  if (raidTypes.includes('RAID10')) {
    if (nvmeCount < 4) {
      errors.push('⚠️ RAID10 requires at least 4 NVMe devices.');
    } else if (nvmeCount % 2 !== 0) {
      errors.push(`⚠️ RAID10 requires an even number of NVMe devices (Current: ${nvmeCount}).`);
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
  const [activeViewMode, setActiveViewMode] = useState('chart'); // Lifted state
  const [config, setConfig] = useState({});
  const [configRef, setConfigRef] = useState(config); // Ref to access latest config in callbacks (Use state for reactivity if needed, or useRef)
  const configRefObj = React.useRef(config); // Renamed to avoid confusion with useState
  const [benchmarkRunning, setBenchmarkRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [currentStage, setCurrentStage] = useState(null); // { stage: 'PD'|'VD', label: '...' }
  const [error, setError] = useState('');
  const [validationErrors, setValidationErrors] = useState([]);
  const [results, setResults] = useState([]);
  const [socket, setSocket] = useState(null);
  const [realTimeData, setRealTimeData] = useState([]);
  const [selectedResults, setSelectedResults] = useState([]);
  const [comparisonData, setComparisonData] = useState({ baseline: null, graid: null });
  const [systemInfo, setSystemInfo] = useState({ nvme_info: [], controller_info: [] });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [activeDevices, setActiveDevices] = useState(new Set());

  useEffect(() => {
    const newSocket = io(API_BASE_URL);
    setSocket(newSocket);

    newSocket.on('connect', () => {
      console.log('Socket connected');
      const sessionId = 'default'; // Using default session for now
      newSocket.emit('join_session', { session_id: sessionId });
    });

    newSocket.on('status', (data) => {
      setStatus(`[${data.timestamp}] ${data.message}`);
      if (data.status === 'completed' || data.status === 'failed') {
        setBenchmarkRunning(false);
        setCurrentStage(null);
      } else if (data.status === 'started') {
        setBenchmarkRunning(true);
        setCurrentStage({ stage: 'INIT', label: 'Initializing...' });
        setRealTimeData([]); // Clear old data
        setActiveDevices(new Set()); // Clear old devices
      }
    });

    newSocket.on('status_update', (data) => {
      setCurrentStage({ stage: data.stage, label: data.label });
    });

    newSocket.on('giostat_data', (data) => {
      parseGiostatLine(data.line);
    });

    // Listen for snapshot trigger
    newSocket.on('snapshot_request', (data) => {
      console.log('Received snapshot request:', data);
      handleSnapshot(data);
    });

    loadConfig();
    loadSystemInfo();
    checkBenchmarkStatus();

    return () => newSocket.close();
  }, []);

  // Set default values for controller and VD name
  useEffect(() => {
    setConfig(prev => {
      const updates = {};
      let changed = false;
      if (!prev.RAID_CTRLR && systemInfo.controller_info.length > 0) {
        updates.RAID_CTRLR = systemInfo.controller_info[0].Name;
        changed = true;
      }
      if (!prev.VD_NAME) {
        updates.VD_NAME = 'gdg0n1';
        changed = true;
      }
      return changed ? { ...prev, ...updates } : prev;
    });
  }, [systemInfo.controller_info]);

  const loadSystemInfo = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/system-info`);
      if (response.data.success) {
        setSystemInfo(response.data.data);
      }
    } catch (err) {
      console.error('Loading system info failed:', err);
    }
  };

  const parseGiostatLine = (line) => {
    // Basic parsing for iostat -xmcd 1 output
    const parts = line.trim().split(/\s+/);
    if (parts.length < 12) return; // Not a valid data line
    if (parts[0] === 'Device' || parts[0] === 'avg-cpu:') return; // Header

    // Check if it matches our target device
    const targetDevice = config.VD_NAME || 'nvme';
    const devName = parts[0];

    // Strict filter based on test configuration
    let isMatch = false;

    // Determine which devices are relevant for the current test config
    // Use configRef.current to get the latest config inside local closure
    const currentConfig = configRef.current || {};
    const runPD = currentConfig.RUN_PD !== false; // Default to true if undefined
    const runVD = currentConfig.RUN_VD !== false; // Default to true if undefined
    const nvmeList = currentConfig.NVME_LIST || [];
    const vdName = currentConfig.VD_NAME || 'gdg0n1';

    // If RUN_PD is active, check against NVME_LIST
    if (runPD) {
      if (nvmeList.length > 0) {
        // Exact or includes match for selected devices
        if (nvmeList.some(d => devName.includes(d))) isMatch = true;
      } else {
        // Fallback: if list empty but PD test active, maybe show all nvme?
        // But user asked for "tested devices only". If empty, arguably nothing is tested.
        // We'll keep the old behavior of accepting all nvme if list is empty to be safe, 
        // OR better: strict match only if list exists.
        // Let's stick to strict if list exists. If list empty, we ignore PDs to avoid clutter?
        // Actually, if list is empty, the benchmark script might select ALL. 
        // Let's assume emptiness means "all" or "none". 
        // Usage pattern implies user selects devices.
        if (devName.startsWith('nvme')) isMatch = true;
      }
    }

    // If RUN_VD is active, check against VD_NAME
    if (runVD) {
      if (devName.includes(vdName)) isMatch = true;
    }

    // Special case: if NO specific filtering (default state), show nvme and gdg/md to be helpful
    if (!currentConfig.RUN_PD && !currentConfig.RUN_VD && !currentConfig.NVME_LIST) {
      // Only if config is truly empty/default, to avoid noise at start
      if (Object.keys(currentConfig).length === 0 && (devName.startsWith('nvme') || devName.startsWith('gdg'))) {
        isMatch = true;
      }
    }

    if (isMatch) {
      setActiveDevices(prev => new Set(prev).add(devName));

      const timestamp = new Date().toLocaleTimeString();
      const iops_read = parseFloat(parts[1]);
      const bw_read = parseFloat(parts[2]);
      const lat_read = parseFloat(parts[5]);
      const iops_write = parseFloat(parts[7]);
      const bw_write = parseFloat(parts[8]);
      const lat_write = parseFloat(parts[11]);

      setRealTimeData(prev => {
        const last = prev[prev.length - 1];

        // If we have a last entry and this device is NOT yet in it, merge it.
        // Otherwise (device already matches or no last entry), create new entry.
        // We assume "timestamp" is close enough for grouping.
        // Better heuristic: Check if `devName` data is already present in `last`.
        let shouldMerge = false;

        if (last) {
          // Check if this device is already in the last record
          const alreadyHasDevice = Object.keys(last).some(k => k.startsWith(`${devName}_`));
          if (!alreadyHasDevice) {
            shouldMerge = true;
          }
        }

        if (shouldMerge) {
          const updatedLast = {
            ...last,
            [`${devName}_iops_read`]: iops_read,
            [`${devName}_bw_read`]: bw_read,
            [`${devName}_lat_read`]: lat_read,
            [`${devName}_iops_write`]: iops_write,
            [`${devName}_bw_write`]: bw_write,
            [`${devName}_lat_write`]: lat_write,
          };
          // Replace last entry
          return [...prev.slice(0, -1), updatedLast];
        } else {
          // Create new entry
          const newData = {
            timestamp,
            [`${devName}_iops_read`]: iops_read,
            [`${devName}_bw_read`]: bw_read,
            [`${devName}_lat_read`]: lat_read,
            [`${devName}_iops_write`]: iops_write,
            [`${devName}_bw_write`]: bw_write,
            [`${devName}_lat_write`]: lat_write,
          };
          const newDataArray = [...prev, newData];
          if (newDataArray.length > 50) newDataArray.shift(); // Keep last 50 points
          return newDataArray;
        }
      });
    }
  };


  const loadConfig = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/config`);
      if (response.data.success) {
        setConfig(response.data.data);
        configRef.current = response.data.data; // Sync ref
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

    // Sanitize NVME_LIST against currently detected devices
    if (systemInfo.nvme_info.length > 0) {
      const validDevices = systemInfo.nvme_info.map(d => d.DevPath.split('/').pop());
      if (Array.isArray(processed.NVME_LIST)) {
        processed.NVME_LIST = processed.NVME_LIST.filter(dev => validDevices.includes(dev));
      }
    }

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
      const errorMsg = err.response?.data?.error || err.message;
      setError('❌ Starting benchmark failed: ' + errorMsg);
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

  const handleSnapshot = async (data) => {
    try {
      // 1. Ensure we are on the Benchmark tab
      setActiveTab('benchmark');

      // 2. Force "Report View" (cdm)
      setActiveViewMode('cdm');

      // 3. Wait for React to render the new view
      await new Promise(resolve => setTimeout(resolve, 800));

      // 4. Capture
      // Target the Metric View specifically
      let element = document.querySelector('.cdm-grid');

      if (!element) {
        console.warn('.cdm-grid not found, trying .realtime-dashboard');
        element = document.querySelector('.realtime-dashboard');
      }

      if (!element) {
        console.warn('.realtime-dashboard not found, falling back to body');
        element = document.body;
      }

      if (!element) return;

      const canvas = await html2canvas(element, {
        useCORS: true,
        logging: false,
        backgroundColor: '#1a1a1a', // Dark background for dark mode theme
        scale: 2 // High resolution
      });

      const imageData = canvas.toDataURL('image/png');

      await axios.post(`${API_BASE_URL}/api/benchmark/save_snapshot`, {
        image: imageData,
        test_name: data.test_name,
        output_dir: data.output_dir
      });

      console.log('Snapshot uploaded successfully');
      setStatus('📸 Snapshot saved');
      setTimeout(() => setStatus(''), 2000);

    } catch (err) {
      console.error('Snapshot capture failed:', err);
    }
  };

  const handleConfigChange = (key, value) => {
    setConfig(prev => {
      const newConfig = { ...prev, [key]: value };
      // Auto-set NVME_INFO based on selected devices if it's the first time
      if (key === 'NVME_LIST' && Array.isArray(value) && value.length > 0 && !prev.NVME_INFO) {
        const firstDev = systemInfo.nvme_info.find(d => d.DevPath.includes(value[0]));
        if (firstDev) newConfig.NVME_INFO = firstDev.Model.replace(/\s+/g, '-');
      }
      configRef.current = newConfig; // Update ref
      return newConfig;
    });
    setValidationErrors([]); // 清除验证错误
  };

  const toggleSelection = (key, value) => {
    setConfig(prev => {
      const current = Array.isArray(prev[key]) ? prev[key] : [];
      const next = current.includes(value)
        ? current.filter(v => v !== value)
        : [...current, value];

      const newConfig = { ...prev, [key]: next };
      configRef.current = newConfig; // Sync ref

      // Auto-update NVME_INFO when NVME_LIST changes
      if (key === 'NVME_LIST') {
        if (next.length > 0) {
          // Find the model of the first selected device
          const firstDevName = next[0];
          const device = systemInfo.nvme_info.find(d => d.DevPath.endsWith(firstDevName));
          if (device) {
            // Replace spaces with hyphens to avoid script issues
            newConfig.NVME_INFO = device.Model.replace(/\s+/g, '-');
          }
        }
      }

      return newConfig;
    });
    setValidationErrors([]);
  };

  const handleArrayChange = (key, value) => {
    setConfig(prev => {
      const next = { ...prev, [key]: value };
      configRef.current = next;
      return next;
    });
    setValidationErrors([]);
  };

  const handleArrayBlur = (key, value) => {
    const array = value.split(',').map(s => s.trim()).filter(s => s);
    setConfig(prev => {
      const next = { ...prev, [key]: array };
      configRef.current = next;
      return next;
    });
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
        configRef.current = processed; // Sync ref
        setStatus('✅ Config saved successfully');
        setError('');
        setValidationErrors([]);
        setTimeout(() => setStatus(''), 3000);
      }
    } catch (err) {
      setError('❌ Failed to save config: ' + err.message);
    }
  };

  const handleResultSelect = (type, value) => {
    const newSelection = [...selectedResults];
    if (type === 'baseline') newSelection[0] = value;
    else newSelection[1] = value;
    setSelectedResults(newSelection);
  };

  const loadComparisonData = async () => {
    if (!selectedResults[0] || !selectedResults[1]) {
      setError('Please select two results to compare');
      return;
    }

    try {
      // Fetch data for both results
      // We assume the backend has an endpoint to get the parsed CSV data
      // If not, we might need to fetch the CSV file and parse it here.
      // Let's assume we added an endpoint /api/results/:name/data

      const [res1, res2] = await Promise.all([
        axios.get(`${API_BASE_URL}/api/results/${selectedResults[0]}/data?type=baseline`),
        axios.get(`${API_BASE_URL}/api/results/${selectedResults[1]}/data?type=graid`)
      ]);

      if (res1.data.success && res2.data.success) {
        setComparisonData({
          baseline: res1.data.data,
          graid: res2.data.data
        });
        setError('');
      }
    } catch (err) {
      setError('Failed to load comparison data: ' + err.message);
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
              <div className="config-header">
                <h2>Configuration Editor</h2>
                <div className="config-actions-top">
                  <button className="btn btn-primary" onClick={saveConfig}>💾 Save</button>
                  <button className="btn btn-secondary" onClick={loadConfig}>🔄 Reload</button>
                </div>
              </div>

              {(() => {
                const currentErrors = validateConfig(processArrayFields(config));
                if (currentErrors.length > 0) {
                  return (
                    <div className="validation-errors">
                      <h4>⚠️ Please fix configuration errors:</h4>
                      <ul>
                        {currentErrors.map((err, idx) => (
                          <li key={idx}>{err}</li>
                        ))}
                      </ul>
                    </div>
                  );
                }
                return null;
              })()}

              <div className="config-form">
                {/* 1. NVMe Device Selection */}
                <div className="config-section">
                  <h3>💽 NVMe Device List</h3>
                  <p className="section-desc">Select the NVMe devices you want to include in the benchmark.</p>
                  <div className="nd-scanner">
                    <table>
                      <thead>
                        <tr>
                          <th>Selected</th>
                          <th>Device</th>
                          <th>Model</th>
                          <th>Capacity</th>
                          <th>NUMA</th>
                        </tr>
                      </thead>
                      <tbody>
                        {systemInfo.nvme_info.map((dev, idx) => (
                          <tr key={idx} onClick={() => toggleSelection('NVME_LIST', dev.DevPath.split('/').pop())} className={(config.NVME_LIST || []).includes(dev.DevPath.split('/').pop()) ? 'selected' : ''}>
                            <td>
                              <input
                                type="checkbox"
                                checked={(config.NVME_LIST || []).includes(dev.DevPath.split('/').pop())}
                                readOnly
                              />
                            </td>
                            <td>{dev.DevPath}</td>
                            <td>{dev.Model}</td>
                            <td>{(dev.Capacity / (1024 ** 3)).toFixed(2)} GiB</td>
                            <td>{dev.Numa}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {systemInfo.nvme_info.length === 0 && <p className="empty-info">No NVMe devices detected by graidctl.</p>}
                </div>

                {/* 2. RAID Controller & 3. VD Name (Hidden/Auto) */}
                <div className="config-section">
                  <h3>🎮 RAID Controller</h3>
                  <div className="controller-info-box">
                    {systemInfo.controller_info.length > 0 ? (
                      systemInfo.controller_info.map((cx, i) => (
                        <div key={i} className="cx-item">
                          <strong>Model:</strong> {cx.Name} | <strong>Serial:</strong> {cx.Sn} | <strong>State:</strong> {cx.State}
                        </div>
                      ))
                    ) : (
                      <p>Detecting controller...</p>
                    )}
                  </div>
                </div>

                {/* 4. RAID Type Selection */}
                <div className="config-section">
                  <h3>🔧 RAID Type Selection</h3>
                  <p className="section-desc">Select one or more RAID levels to test.</p>
                  <div className="button-group-select">
                    {['RAID0', 'RAID1', 'RAID5', 'RAID6', 'RAID10'].map(type => (
                      <button
                        key={type}
                        className={`selection-btn ${(config.RAID_TYPE || []).includes(type) ? 'active' : ''}`}
                        onClick={() => toggleSelection('RAID_TYPE', type)}
                      >
                        {type}
                      </button>
                    ))}
                  </div>
                </div>

                {/* 5. Advanced Options */}
                <div className="config-section">
                  <div className="section-header-toggle" onClick={() => setShowAdvanced(!showAdvanced)}>
                    <h3>⚙️ Advanced Options</h3>
                    <span>{showAdvanced ? '▼' : '▶'}</span>
                  </div>

                  {showAdvanced && (
                    <div className="advanced-content">
                      <div className="form-group">
                        <label>Status List (Wait for State):</label>
                        <div className="button-group-select">
                          {['Normal', 'Rebuild'].map(item => (
                            <button
                              key={item}
                              className={`selection-btn ${(config.STA_LS || []).includes(item) ? 'active' : ''}`}
                              onClick={() => toggleSelection('STA_LS', item)}
                            >
                              {item}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="form-group">
                        <label>Test Stages:</label>
                        <div className="button-group-select">
                          {['afterdiscard', 'afterprecondition', 'aftersustain'].map(item => (
                            <button
                              key={item}
                              className={`selection-btn ${(config.TS_LS || []).includes(item) ? 'active' : ''}`}
                              onClick={() => toggleSelection('TS_LS', item)}
                            >
                              {item}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="grid-2-cols">
                        <div className="form-group">
                          <label>QD List:</label>
                          <input
                            type="text"
                            value={getArrayDisplayValue(config.QD_LS)}
                            onChange={(e) => handleArrayChange('QD_LS', e.target.value)}
                            onBlur={(e) => handleArrayBlur('QD_LS', e.target.value)}
                          />
                        </div>
                        <div className="form-group">
                          <label>PD Jobs:</label>
                          <input
                            type="text"
                            value={getArrayDisplayValue(config.pd_jobs)}
                            onChange={(e) => handleArrayChange('pd_jobs', e.target.value)}
                            onBlur={(e) => handleArrayBlur('pd_jobs', e.target.value)}
                          />
                        </div>
                      </div>

                      <div className="grid-2-cols">
                        <div className="form-group">
                          <label>PD Runtime (s):</label>
                          <input
                            type="number"
                            value={config.PD_RUNTIME || 180}
                            onChange={(e) => handleConfigChange('PD_RUNTIME', parseInt(e.target.value))}
                          />
                        </div>
                        <div className="form-group">
                          <label>VD Runtime (s):</label>
                          <input
                            type="number"
                            value={config.VD_RUNTIME || 180}
                            onChange={(e) => handleConfigChange('VD_RUNTIME', parseInt(e.target.value))}
                          />
                        </div>
                      </div>

                      {/* 6. Test Switches */}
                      <div className="switches-grid">
                        {[
                          { key: 'QUICK_TEST', label: 'Quick Test' },
                          { key: 'LOG_COMPACT', label: 'Compact Log' },
                          { key: 'SCAN', label: 'Full Scan' },
                          { key: 'RUN_PD', label: 'Run PD Test' },
                          { key: 'RUN_VD', label: 'Run VD Test' },
                          { key: 'RUN_PD_ALL', label: 'Test All PDs' }
                        ].map(sw => (
                          <label key={sw.key} className="switch-label">
                            <input
                              type="checkbox"
                              checked={config[sw.key] !== false}
                              onChange={(e) => handleConfigChange(sw.key, e.target.checked)}
                            />
                            {sw.label}
                          </label>
                        ))}
                      </div>
                    </div>
                  )}
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

              {(() => {
                const currentErrors = validateConfig(processArrayFields(config));
                if (currentErrors.length > 0) {
                  return (
                    <div className="validation-errors">
                      <h4>⚠️ Please fix configuration errors before starting:</h4>
                      <ul>
                        {currentErrors.map((err, idx) => (
                          <li key={idx}>{err}</li>
                        ))}
                      </ul>
                    </div>
                  );
                }
                return null;
              })()}


              <div className="test-status-container">
                {benchmarkRunning ? (
                  <div className="status-split-container">
                    <div className="status-box status-general-running">
                      <div className="status-label">RUN STATUS</div>
                      <div className="status-value">
                        BENCHMARKING
                        <div className="status-spinner-small"></div>
                      </div>
                    </div>
                    <div className={`status-box ${currentStage?.stage === 'PD' ? 'status-stage-pd' : currentStage?.stage === 'VD' ? 'status-stage-vd' : 'status-stage-init'}`}>
                      <div className="status-label">CURRENT STAGE</div>
                      <div className="status-value">{currentStage?.label || 'Initializing...'}</div>
                    </div>
                  </div>
                ) : (
                  <div className="status-box status-idle">
                    <div className="status-label">RUN STATUS</div>
                    <div className="status-value">READY</div>
                  </div>
                )}
              </div>
              <div className="control-buttons">
                <button
                  className="btn btn-success"
                  onClick={handleStartTest}
                  disabled={benchmarkRunning || validateConfig(processArrayFields(config)).length > 0}
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

              <div className="realtime-dashboard">
                <h3>Real-time Monitor</h3>
                <RealTimeDashboard
                  data={realTimeData}
                  devices={Array.from(activeDevices)}
                  viewMode={activeViewMode}
                  setViewMode={setActiveViewMode}
                />
              </div>
            </div>
          )}

          {activeTab === 'results' && (
            <div className="results-panel">
              <h2>Test Results</h2>

              <div className="comparison-controls">
                <h3>Compare Results</h3>
                <div className="selection-group">
                  <select
                    onChange={(e) => handleResultSelect('baseline', e.target.value)}
                    value={selectedResults[0] || ''}
                  >
                    <option value="">Select Baseline (e.g. PD)</option>
                    {results.map((r, i) => (
                      <option key={i} value={r.name}>{r.name}</option>
                    ))}
                  </select>

                  <select
                    onChange={(e) => handleResultSelect('graid', e.target.value)}
                    value={selectedResults[1] || ''}
                  >
                    <option value="">Select Graid (e.g. VD)</option>
                    {results.map((r, i) => (
                      <option key={i} value={r.name}>{r.name}</option>
                    ))}
                  </select>

                  <button className="btn btn-primary" onClick={loadComparisonData}>
                    Compare
                  </button>
                </div>

                {comparisonData.baseline && comparisonData.graid && (
                  <ComparisonDashboard
                    baselineData={comparisonData.baseline}
                    graidData={comparisonData.graid}
                  />
                )}
              </div>

              <h3>All Results</h3>
              {results.length === 0 ? (
                <p className="empty-message">No results found</p>
              ) : (
                <div className="results-list">
                  {results.map((result, idx) => (
                    <div key={idx} className="result-item">
                      <h3>{result.name}</h3>
                      <p>Testing Time: {result.created}</p>
                      <p>Files: {result.files ? result.files.length : 'N/A'}</p>
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
    </div >
  );
}

export default App;