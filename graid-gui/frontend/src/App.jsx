import React, { useState, useEffect } from 'react';
import axios from 'axios';
import html2canvas from 'html2canvas';
import './App.css';
import io from 'socket.io-client';
import RealTimeDashboard from './components/RealTimeDashboard';
import ComparisonDashboard from './components/ComparisonDashboard';
import TheoreticalCalculator from './components/TheoreticalCalculator';
import HelpButton from './components/HelpButton';
import { helpContent } from './utils/helpContent';

const API_BASE_URL = `http://${window.location.hostname}:50071`;

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

const SENSITIVE_PARAMS = [
  'DUT_PASSWORD',
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
  const [activeTab, setActiveTab] = useState(localStorage.getItem('activeTab') || 'config');
  const [activeViewMode, setActiveViewMode] = useState('chart'); // Lifted state
  const [config, setConfig] = useState(() => {
    const savedConfig = localStorage.getItem('configDraft');
    return savedConfig ? JSON.parse(savedConfig) : {};
  });
  const [configRef, setConfigRef] = useState(config); // Ref to access latest config in callbacks (Use state for reactivity if needed, or useRef)
  const configRefObj = React.useRef(config); // Renamed to avoid confusion with useState
  const [benchmarkRunning, setBenchmarkRunning] = useState(false);
  const [status, setStatus] = useState('');
  const [currentStage, setCurrentStage] = useState(null); // { stage: 'PD'|'VD', label: '...' }
  const currentStageRef = React.useRef(null);
  const [runStatus, setRunStatus] = useState('BENCHMARKING');
  const [progress, setProgress] = useState({ percentage: 0, elapsed: 0, remaining: 0, current_step: 0, total_steps: 0 });
  const [error, setError] = useState('');
  const [validationErrors, setValidationErrors] = useState([]);
  const [results, setResults] = useState([]);
  const [socket, setSocket] = useState(null);
  const [realTimeData, setRealTimeData] = useState([]);
  const [selectedResults, setSelectedResults] = useState([]);
  const [comparisonData, setComparisonData] = useState({ baseline: null, graid: null, baselineMetadata: null, graidMetadata: null });
  const [loadingResults, setLoadingResults] = useState(false);
  const [reportImages, setReportImages] = useState([]);
  const [activeResultTab, setActiveResultTab] = useState('dashboard'); // 'dashboard' or 'gallery'
  const [systemInfo, setSystemInfo] = useState({ nvme_info: [], controller_info: [] });
  const [language, setLanguage] = useState('TW');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [activeDevices, setActiveDevices] = useState(new Set());
  const [licenseInfo, setLicenseInfo] = useState({});
  const [advancedLogs, setAdvancedLogs] = useState([]);
  const [showAdvancedLog, setShowAdvancedLog] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [galleryFilters, setGalleryFilters] = useState({ raid: 'All', status: 'All', type: 'All' });
  const [connectionStatus, setConnectionStatus] = useState(() => {
    const saved = localStorage.getItem('connectionStatus');
    return saved ? JSON.parse(saved) : { loading: false, success: null, message: '', dependencies: null };
  });
  const logEndRef = React.useRef(null);
  const [nvmeSortConfig, setNvmeSortConfig] = useState({ key: 'DevPath', direction: 'asc' });

  const sortedNvmeInfo = React.useMemo(() => {
    if (!systemInfo.nvme_info) return [];

    return [...systemInfo.nvme_info].sort((a, b) => {
      const { key, direction } = nvmeSortConfig;

      let valA = a[key];
      let valB = b[key];

      // Handle missing values
      if (valA === undefined || valA === null) valA = '';
      if (valB === undefined || valB === null) valB = '';

      let comparison = 0;

      // Special handling for numeric fields
      if (key === 'Capacity' || key === 'Numa') {
        comparison = (Number(valA) || 0) - (Number(valB) || 0);
      } else {
        // String comparison with numeric awareness (e.g. nvme0n1 vs nvme0n10)
        comparison = String(valA).localeCompare(String(valB), undefined, { numeric: true, sensitivity: 'base' });
      }

      return direction === 'asc' ? comparison : -comparison;
    });
  }, [systemInfo.nvme_info, nvmeSortConfig]);

  const handleSort = (key) => {
    setNvmeSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
  };

  const SortButton = ({ columnKey, currentConfig }) => {
    const isActive = currentConfig.key === columnKey;
    return (
      <button
        type="button"
        onClick={() => handleSort(columnKey)}
        style={{
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          marginLeft: '5px',
          fontSize: '12px',
          padding: '0 4px',
          color: isActive ? '#007bff' : '#ccc',
          fontWeight: isActive ? 'bold' : 'normal'
        }}
        title={`Sort by ${columnKey}`}
      >
        {isActive ? (currentConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
      </button>
    );
  };

  const loadConfig = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/config`);
      if (response.data.success) {
        setConfig(response.data.data);
        configRefObj.current = response.data.data; // Sync ref
        setError('');
      }
    } catch (err) {
      setError('Loading config failed: ' + err.message);
    }
  };

  const loadSystemInfo = async (cfg = null) => {
    try {
      const currentCfg = cfg || configRefObj.current;
      const response = await axios.post(`${API_BASE_URL}/api/system-info`, {
        config: currentCfg
      });
      if (response.data.success) {
        setSystemInfo(response.data.data);
      }
    } catch (err) {
      console.error('Loading system info failed:', err);
    }
  };

  const loadLicenseInfo = async (cfg = null) => {
    try {
      const currentCfg = cfg || configRefObj.current;
      const response = await axios.post(`${API_BASE_URL}/api/license-info`, {
        config: currentCfg
      });
      if (response.data.success) {
        setLicenseInfo(response.data.data);
      }
    } catch (err) {
      console.error('Loading license info failed:', err);
    }
  };

  const fetchLogs = async () => {
    try {
      const res = await axios.get(`${API_BASE_URL}/api/benchmark/logs`);
      if (res.data.success) {
        setAdvancedLogs(res.data.logs);
      }
    } catch (err) {
      console.error('Failed to fetch logs:', err);
    }
  };

  const checkBenchmarkStatus = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/benchmark/status`);
      if (response.data.success && response.data.data.running) {
        setBenchmarkRunning(true);

        // Restore progress if available
        if (response.data.data.progress) {
          setProgress(response.data.data.progress);
        }

        // Set a recovering status indicator
        // Use recovered stage info if available
        if (response.data.data.stage_info && response.data.data.stage_info.label) {
          const sInfo = response.data.data.stage_info;
          setCurrentStage(sInfo);
          currentStageRef.current = sInfo;
        } else {
          setCurrentStage({ stage: 'VD', label: 'Recovering session...' });
          currentStageRef.current = { stage: 'VD', label: 'Recovering session...' };
        }

        loadSystemInfo(); // Refresh system info to get latest remote hostname if any

        if (response.data.data.recovered) {
          setStatus(`[${new Date().toISOString()}] Benchmark session recovered`);
        }

        return response.data.data;
      }
    } catch (err) {
      console.error('Check status failed:', err);
    }
    return null;
  };

  const handleSnapshot = async (data = {}) => {
    try {
      // 1. Save current view mode
      const previousViewMode = activeViewMode;

      // 2. Force switch to Report View (CDM Grid) - User requirement: Always capture Report View
      if (previousViewMode !== 'cdm') {
        setActiveViewMode('cdm');
        // Wait for React to render the new view
        await new Promise(resolve => setTimeout(resolve, 500));
      }

      // Add a small delay to ensure DOM is updated
      await new Promise(resolve => setTimeout(resolve, 200));

      // Find the dashboard or report element
      let element = document.querySelector('.cdm-grid');
      // If CDM grid not found (fallback), look for dashboard classes
      if (!element) element = document.querySelector('.dashboard-grid') || document.querySelector('.dashboard-wrapper');

      if (!element) {
        console.warn('Snapshot failed: No target element found');
        // Restore view if we switched
        if (previousViewMode !== 'cdm') setActiveViewMode(previousViewMode);
        return;
      }

      console.log(`Taking snapshot for ${data.test_name} using element:`, element.className);
      const canvas = await html2canvas(element, {
        logging: false,
        useCORS: true,
        allowTaint: true
      });
      const imgData = canvas.toDataURL('image/png');

      // 3. Restore original view mode
      if (previousViewMode !== 'cdm') {
        setActiveViewMode(previousViewMode);
      }

      const response = await axios.post(`${API_BASE_URL}/api/benchmark/save_snapshot`, {
        image: imgData,
        test_name: data.test_name,
        output_dir: data.output_dir,
        session_id: data.session_id || 'default'
      });

      if (response.data.success) {
        console.log('Snapshot saved and synced successfully');
      }
    } catch (err) {
      console.error('Snapshot failed:', err);
    }
  };

  const updateRealTimeData = (data) => {
    const devName = data.dev;

    // Strict filter based on test configuration
    let isMatch = false;

    // Determine which devices are relevant for the current test config
    // CRITICAL: Use the latest config from the ref to avoid closure traps
    const currentConfig = configRefObj.current || {};
    const runPD = currentConfig.RUN_PD !== false;
    const runVD = currentConfig.RUN_VD !== false;
    const nvmeList = currentConfig.NVME_LIST || [];
    const vdName = currentConfig.VD_NAME || 'gdg0n1';

    // If RUN_PD is active, check against NVME_LIST
    // Fix: Only show if we are in PD stage or if stage is unknown/init
    const stage = currentStageRef.current?.stage;

    // Filter logic based on Stage
    if (stage === 'PD') {
      if (devName.startsWith('nvme')) {
        // Further filter by selected NVMe list if available
        if (nvmeList.length > 0) {
          if (nvmeList.some(d => devName.includes(d))) isMatch = true;
        } else {
          isMatch = true;
        }
      }
    } else if (stage === 'VD') {
      if (devName.includes(vdName) || devName.startsWith('md') || devName.startsWith('gdg') || devName.startsWith('gvo')) {
        isMatch = true;
      }
    } else {
      // Fallback or Init: Show what is configured to run
      if (runPD && devName.startsWith('nvme')) {
        if (nvmeList.length > 0) {
          if (nvmeList.some(d => devName.includes(d))) isMatch = true;
        } else {
          isMatch = true;
        }
      }
      if (runVD && (devName.includes(vdName) || devName.startsWith('gdg'))) {
        isMatch = true;
      }
    }

    if (isMatch) {
      setActiveDevices(prev => new Set(prev).add(devName));

      const timestamp = new Date().toLocaleTimeString();

      setRealTimeData(prev => {
        const last = prev[prev.length - 1];
        let shouldMerge = false;

        if (last) {
          const alreadyHasDevice = Object.keys(last).some(k => k.startsWith(`${devName}_`));
          if (!alreadyHasDevice) {
            shouldMerge = true;
          }
        }

        if (shouldMerge) {
          const updatedLast = {
            ...last,
            [`${devName}_iops_read`]: data.iops_read,
            [`${devName}_bw_read`]: data.bw_read,
            [`${devName}_lat_read`]: data.lat_read,
            [`${devName}_iops_write`]: data.iops_write,
            [`${devName}_bw_write`]: data.bw_write,
            [`${devName}_lat_write`]: data.lat_write,
          };
          return [...prev.slice(0, -1), updatedLast];
        } else {
          const newData = {
            timestamp,
            [`${devName}_iops_read`]: data.iops_read,
            [`${devName}_bw_read`]: data.bw_read,
            [`${devName}_lat_read`]: data.lat_read,
            [`${devName}_iops_write`]: data.iops_write,
            [`${devName}_bw_write`]: data.bw_write,
            [`${devName}_lat_write`]: data.lat_write,
          };
          const newHistory = [...prev, newData];
          return newHistory.slice(-60);
        }
      });
    }
  };

  // Sync refs to avoid closure traps in socket listeners
  const updateRealTimeDataRef = React.useRef(updateRealTimeData);
  const handleSnapshotRef = React.useRef(handleSnapshot);

  useEffect(() => {
    configRefObj.current = config;
  }, [config]);

  useEffect(() => {
    updateRealTimeDataRef.current = updateRealTimeData;
  }, [updateRealTimeData]);

  useEffect(() => {
    handleSnapshotRef.current = handleSnapshot;
  }, [handleSnapshot]);

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
        currentStageRef.current = null;
      } else if (data.status === 'started') {
        setBenchmarkRunning(true);
        setCurrentStage({ stage: 'INIT', label: 'Initializing...' });
        currentStageRef.current = { stage: 'INIT', label: 'Initializing...' };
        setRealTimeData([]); // Clear old data
        setActiveDevices(new Set()); // Clear old devices
        setProgress({ percentage: 0, elapsed: 0, remaining: 0, current_step: 0, total_steps: 0 });
        setRunStatus('BENCHMARKING');
      }
    });

    newSocket.on('progress_update', (data) => {
      setProgress(data);
    });

    newSocket.on('status_update', (data) => {
      setCurrentStage({ stage: data.stage, label: data.label });
      currentStageRef.current = { stage: data.stage, label: data.label };
      // If benchmark started while we were on config tab, maybe we should switch?
      // But typically it starts from the Benchmark tab anyway.
    });

    newSocket.on('run_status_update', (data) => {
      setRunStatus(data.status.toUpperCase());
    });

    newSocket.on('giostat_data_v2', (data) => {
      if (updateRealTimeDataRef.current) {
        updateRealTimeDataRef.current(data);
      }
    });

    newSocket.on('giostat_data', (data) => {
      console.log('Got raw giostat data:', data);
    });

    // Listen for snapshot trigger
    newSocket.on('snapshot_request', (data) => {
      if (handleSnapshotRef.current) {
        handleSnapshotRef.current(data);
      }
    });

    newSocket.on('bench_log', (data) => {
      setAdvancedLogs(prev => {
        const newLogs = [...prev, data.line];
        return newLogs.slice(-20); // Keep last 20 lines (tail -n 20)
      });
    });

    const fetchLogs = async () => {
      try {
        const res = await axios.get(`${API_BASE_URL}/api/benchmark/logs`);
        if (res.data.success) {
          setAdvancedLogs(res.data.logs);
        }
      } catch (err) {
        console.error('Failed to fetch logs:', err);
      }
    };

    const init = async () => {
      // If no saved config draft, load from server
      if (!localStorage.getItem('configDraft')) {
        await loadConfig();
      }

      const status = await checkBenchmarkStatus();
      if (status && status.running) {
        setActiveTab('benchmark');
        fetchLogs();
      }
    };

    init();

    return () => newSocket.close();
  }, []);

  // Save activeTab to localStorage
  useEffect(() => {
    localStorage.setItem('activeTab', activeTab);
  }, [activeTab]);

  // Save config draft to localStorage
  useEffect(() => {
    if (Object.keys(config).length > 0) {
      localStorage.setItem('configDraft', JSON.stringify(config));
    }
  }, [config]);

  // Effect to load system info once config is loaded if we have connection success
  useEffect(() => {
    if (connectionStatus.success && Object.keys(config).length > 0) {
      loadSystemInfo(config);
      loadLicenseInfo(config);
    }
  }, [connectionStatus.success, (config && config.DUT_IP)]);

  // Real-time countdown for remaining time
  useEffect(() => {
    let timer;
    if (benchmarkRunning) {
      timer = setInterval(() => {
        setProgress(prev => {
          if (prev.remaining > 0) {
            return {
              ...prev,
              elapsed: prev.elapsed + 1,
              remaining: prev.remaining - 1
            };
          }
          return {
            ...prev,
            elapsed: prev.elapsed + 1
          };
        });
      }, 1000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [benchmarkRunning]);

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

  // Consolidating configRefObj usage

  // ✅ 添加这个辅助函数
  const processArrayFields = (cfg) => {
    const processed = { ...cfg };
    const arrayFields = ['NVME_LIST', 'RAID_TYPE', 'TS_LS', 'STA_LS', 'JOB_LS', 'QD_LS', 'BS_LS', 'pd_jobs', 'WP_LS'];

    arrayFields.forEach(key => {
      if (typeof processed[key] === 'string') {
        processed[key] = processed[key].split(',').map(s => s.trim()).filter(s => s);
      }
    });

    // Auto-sync LS_JB
    const qdCount = (processed.QD_LS || []).length;
    const pdJobsCount = (processed.pd_jobs || []).length;
    if (qdCount > 1 || pdJobsCount > 1) {
      processed.LS_JB = "true";
    }

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
      setAdvancedLogs([]); // Clear logs when starting
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

  const handleTestConnection = async () => {
    try {
      setConnectionStatus({ loading: true, success: null, message: '' });
      const response = await fetch(`${API_BASE_URL}/api/benchmark/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config })
      });
      const data = await response.json();

      if (data.success) {
        const newStatus = {
          loading: false,
          success: true,
          message: data.message,
          dependencies: data.dependencies
        };
        setConnectionStatus(newStatus);
        localStorage.setItem('connectionStatus', JSON.stringify(newStatus));
        // Success! Reload info from the remote DUT
        await loadSystemInfo(config);
        await loadLicenseInfo(config);
      } else {
        const newStatus = { loading: false, success: false, message: data.error };
        setConnectionStatus(newStatus);
        localStorage.removeItem('connectionStatus');
      }
    } catch (error) {
      setConnectionStatus({ loading: false, success: false, message: error.message });
    }
  };

  const handleSetupDUT = async () => {
    try {
      setConnectionStatus(prev => ({ ...prev, loading: true, message: 'Installing dependencies on DUT...' }));
      const response = await fetch(`${API_BASE_URL}/api/benchmark/setup-dut`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config })
      });
      const data = await response.json();

      if (data.success) {
        setConnectionStatus(prev => ({
          loading: false,
          success: true,
          message: 'Setup complete! Re-testing connection...',
          dependencies: null
        }));
        // Re-test to refresh dependency list
        setTimeout(handleTestConnection, 1000);
      } else {
        setConnectionStatus(prev => ({
          loading: false,
          success: false,
          message: `Setup failed: ${data.error}`
        }));
      }
    } catch (error) {
      setConnectionStatus({ loading: false, success: false, message: error.message });
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

  useEffect(() => {
    if (activeTab === 'results') {
      loadResults();
    }
  }, [activeTab]);


  const handleConfigChange = (key, value) => {
    setConfig(prev => {
      const newConfig = { ...prev, [key]: value };
      // Auto-set NVME_INFO based on selected devices if it's the first time
      if (key === 'NVME_LIST' && Array.isArray(value) && value.length > 0 && !prev.NVME_INFO) {
        const firstDev = systemInfo.nvme_info.find(d => d.DevPath.includes(value[0]));
        if (firstDev) newConfig.NVME_INFO = firstDev.Model.replace(/\s+/g, '-');
      }
      configRefObj.current = newConfig; // Update ref

      // Trigger info reload if switching back to local mode
      if (key === 'REMOTE_MODE' && value === false) {
        setConnectionStatus({ loading: false, success: null, message: '', dependencies: null });
        localStorage.removeItem('connectionStatus');
        loadSystemInfo(newConfig);
        loadLicenseInfo(newConfig);
      }

      return newConfig;
    });
    setValidationErrors([]); // 清除验证错误
  };

  const toggleSelection = (key, value) => {
    setConfig(prev => {
      const current = Array.isArray(prev[key]) ? prev[key] : [];

      // License check for NVME_LIST
      if (key === 'NVME_LIST' && !current.includes(value)) {
        const maxLimit = getMaxPdLimit();
        if (current.length >= maxLimit) {
          setStatus(`⚠️ Cannot select more than ${maxLimit} devices (License Limit).`);
          setTimeout(() => setStatus(''), 3000);
          return prev;
        }
      }

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

  const getMaxPdLimit = () => {
    // Check both 'Features' and 'features' for robust dictionary access
    const features = licenseInfo.Features || licenseInfo.features || {};
    return parseInt(features['NVMe/NVMe-oFPDNumber']) ||
      parseInt(features['NVMe/NVMe-oFPDNumbe']) || 999;
  };

  const handleSelectAllToggle = () => {
    const maxLimit = getMaxPdLimit();
    const allDevices = systemInfo.nvme_info.map(d => d.DevPath.split('/').pop());
    const currentSelected = config.NVME_LIST || [];

    // If all possible are already selected, deselect all
    if (currentSelected.length === Math.min(allDevices.length, maxLimit)) {
      handleConfigChange('NVME_LIST', []);
      return;
    }

    // Otherwise, select up to limit
    const toSelect = allDevices.slice(0, maxLimit);
    if (toSelect.length < allDevices.length) {
      setStatus(`⚠️ License limit reached: Selected top ${maxLimit} devices.`);
      setTimeout(() => setStatus(''), 3000);
    }
    handleConfigChange('NVME_LIST', toSelect);
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

  const handleResetConfig = async () => {
    try {
      setStatus('🔍 Checking Graid resources...');
      // Use POST to pass current config (including unsaved remote settings)
      const checkRes = await axios.post(`${API_BASE_URL}/api/graid/check`, {
        config: config
      });

      if (checkRes.data.success) {
        if (!checkRes.data.has_resources) {
          setStatus('✅ No Graid resources found to reset.');
          setTimeout(() => setStatus(''), 3000);
          return;
        }

        const findings = checkRes.data.findings.join(', ');
        const confirmReset = window.confirm(
          `⚠️ WARNING: Existing Graid resources found (${findings}).\n\n` +
          `This will delete ALL Virtual Disks, Drive Groups, and Physical Disk configurations.\n` +
          `Are you sure you want to proceed with the reset?`
        );

        if (confirmReset) {
          setIsResetting(true); // Set resetting state to true
          setStatus('♻️ Resetting Graid resources...');
          const resetRes = await axios.post(`${API_BASE_URL}/api/graid/reset`, {
            config: config
          });
          if (resetRes.data.success) {
            setStatus('✅ Graid resources cleared successfully');
            loadSystemInfo(config); // Refresh device lists with current config
            setTimeout(() => setStatus(''), 3000);
          }
          setIsResetting(false); // Reset state after completion
        } else {
          setStatus('Reset cancelled.');
          setTimeout(() => setStatus(''), 2000);
        }
      }
    } catch (err) {
      setIsResetting(false); // Reset state on error
      setError('❌ Reset failed: ' + (err.response?.data?.error || err.message));
    }
  };

  const handleResultSelect = (name) => {
    setSelectedResults([name]);
    setComparisonData({ baseline: null, graid: null, baselineMetadata: null, graidMetadata: null });
    setReportImages([]); // Clear images when selecting a new result
    setActiveResultTab('dashboard'); // Reset to dashboard view
  };

  const loadComparisonData = async () => {
    if (!selectedResults[0]) {
      setError('Please select a result to view');
      return;
    }

    const resultName = selectedResults[0];
    setLoadingResults(true);
    setError('');

    try {
      const [res1, res2, resImg] = await Promise.all([
        axios.get(`${API_BASE_URL}/api/results/${resultName}/data?type=baseline`),
        axios.get(`${API_BASE_URL}/api/results/${resultName}/data?type=graid`),
        axios.get(`${API_BASE_URL}/api/results/${resultName}/images`)
      ]);

      if (resImg.data.success) {
        setReportImages(resImg.data.images);
      }

      // Baseline is optional now, graid is required for a valid view
      if (res2.data.success) {
        // Metadata extraction helper
        // Metadata extraction helper
        const extractMetadata = (resultData, resultName) => {
          if (resultData && resultData.length > 0) {
            const row = resultData[0];
            // Try to use CSV columns if available and valid
            if (row.RAID_type && row.PD_count) {
              return {
                raidType: row.RAID_type,
                pdCount: parseInt(row.PD_count) || 12
              };
            }
          }

          // Fallback to parsing filename
          const parts = resultName.split('-');
          const raidPart = parts.find(p => p.startsWith('RAID'));
          const pdPart = parts.find(p => p.endsWith('PD'));
          return {
            raidType: raidPart || 'RAID0',
            pdCount: pdPart ? parseInt(pdPart.replace('PD', '')) : 12
          };
        };

        // Extract metadata from both results
        const baselineMetadata = res1.data.success ? extractMetadata(res1.data.data, resultName) : null;
        const graidMetadata = extractMetadata(res2.data.data, resultName);

        setComparisonData({
          baseline: res1.data.success ? res1.data.data : null,
          graid: res2.data.data,
          baselineMetadata,
          graidMetadata
        });
        setError('');
      } else {
        setError('Failed to load comparison data: ' + (res1.data.error || res2.data.error || 'Unknown backend error'));
      }
    } catch (err) {
      setError('Failed to load comparison data: ' + err.message);
    } finally {
      setLoadingResults(false);
    }
  };

  const formatTime = (seconds) => {
    if (isNaN(seconds) || seconds < 0) return '??:??:??';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>🚀 SupremeRAID Benchmark Web GUI</h1>
        <div className="header-controls">
          <div className="header-status">
            {benchmarkRunning ? (
              <span className="status-running">● Running</span>
            ) : (
              <span className="status-idle">● Standby</span>
            )}
            <div className="connection-info">
              {config.REMOTE_MODE ? (
                <span>
                  <i className="mode-remote">Remote Mode</i>: {config.DUT_IP}
                  {systemInfo.hostname && ` (${systemInfo.hostname})`}
                </span>
              ) : (
                <i className="mode-local">Local Mode</i>
              )}
            </div>
          </div>
          <HelpButton
            title={helpContent[language][activeTab]?.title || "Help"}
            content={helpContent[language][activeTab] || { sections: [] }}
            language={language}
            setLanguage={setLanguage}
          />
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
          <button
            className={`tab-button ${activeTab === 'calculator' ? 'active' : ''}`}
            onClick={() => setActiveTab('calculator')}
          >
            🧮 Calculator
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
                  <button className="btn btn-danger" onClick={handleResetConfig} title="Clear existing VD/DG/PD configurations">♻️ Reset</button>
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
                {/* 0. Target Machine Setup */}
                <div className="config-section">
                  <h3>🖥️ Target Machine Setup</h3>
                  <p className="section-desc">Configure where the benchmark should run (Local or Remote DUT).</p>
                  <div className="form-group">
                    <label className="switch-label">
                      <input
                        type="checkbox"
                        checked={config.REMOTE_MODE === true}
                        onChange={(e) => handleConfigChange('REMOTE_MODE', e.target.checked)}
                      />
                      Enable Remote DUT Mode
                    </label>
                  </div>

                  {config.REMOTE_MODE && (
                    <div className="remote-setup-grid grid-2-cols" style={{ marginTop: '15px', background: 'rgba(255,255,255,0.03)', padding: '15px', borderRadius: '8px' }}>
                      <div className="form-group">
                        <label>DUT IP Address:</label>
                        <input
                          type="text"
                          placeholder="e.g. 192.168.1.100"
                          value={config.DUT_IP || ''}
                          onChange={(e) => handleConfigChange('DUT_IP', e.target.value)}
                        />
                      </div>
                      <div className="form-group">
                        <label>SSH Port:</label>
                        <input
                          type="number"
                          placeholder="22"
                          value={config.DUT_PORT || 22}
                          onChange={(e) => handleConfigChange('DUT_PORT', parseInt(e.target.value))}
                        />
                      </div>
                      <div className="form-group">
                        <label>SSH User:</label>
                        <input
                          type="text"
                          placeholder="root"
                          value={config.DUT_USER || 'root'}
                          onChange={(e) => handleConfigChange('DUT_USER', e.target.value)}
                        />
                      </div>
                      <div className="form-group">
                        <label>SSH Password:</label>
                        <input
                          type="password"
                          placeholder="Leave empty if using SSH Keys"
                          value={config.DUT_PASSWORD || ''}
                          onChange={(e) => handleConfigChange('DUT_PASSWORD', e.target.value)}
                        />
                      </div>
                      <div className="form-group" style={{ gridColumn: 'span 2', display: 'flex', gap: '10px' }}>
                        <button
                          className={`btn ${connectionStatus.success ? 'btn-success' : 'btn-secondary'}`}
                          onClick={handleTestConnection}
                          style={{ flex: 1 }}
                          disabled={connectionStatus.loading}
                        >
                          {connectionStatus.loading ? '⏳ Connecting...' : (connectionStatus.success ? '✅ Connected' : '🔗 Connect')}
                        </button>
                      </div>

                      {connectionStatus.message && (
                        <div className={`connection-message ${connectionStatus.success ? 'success' : 'error'}`} style={{ gridColumn: 'span 2' }}>
                          {connectionStatus.message}
                        </div>
                      )}

                      {connectionStatus.dependencies && (
                        <div className="dependency-check" style={{ gridColumn: 'span 2', marginTop: '10px' }}>
                          {(() => {
                            const allPassed = Object.values(connectionStatus.dependencies).every(v => v === true);
                            return (
                              <>
                                <h4 style={{ fontSize: '14px', marginBottom: '8px' }}>
                                  📦 Dependency Check: <span style={{ color: allPassed ? '#52c41a' : '#ff4d4f' }}>{allPassed ? 'Success' : 'Failed'}</span>
                                </h4>

                                {!allPassed && (
                                  <div style={{ marginTop: '15px', padding: '10px', background: 'rgba(24, 144, 255, 0.1)', borderRadius: '4px', border: '1px solid rgba(24, 144, 255, 0.2)' }}>
                                    <p style={{ fontSize: '12px', marginBottom: '10px', color: '#1890ff' }}>
                                      Some dependencies are missing.
                                    </p>
                                    <button
                                      className="btn btn-primary"
                                      onClick={handleSetupDUT}
                                      disabled={connectionStatus.loading}
                                      style={{ width: '100%' }}
                                    >
                                      {connectionStatus.loading ? '⏳ Installing...' : '🚀 Execute Installation'}
                                    </button>
                                  </div>
                                )}
                              </>
                            );
                          })()}
                        </div>
                      )}

                      {!connectionStatus.success && (
                        <div className="form-group" style={{ gridColumn: 'span 2' }}>
                          <p style={{ fontSize: '12px', color: '#888', fontStyle: 'italic' }}>
                            Note: Ensure the host machine (backend container) can reach the DUT via SSH.
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                {/* 1. NVMe Device Selection */}
                <div className="config-section">
                  <div className="section-header-row">
                    <h3>💽 NVMe Device List ({
                      (config.NVME_LIST || []).filter(dev =>
                        systemInfo.nvme_info.some(sysDev => sysDev.DevPath.endsWith(dev))
                      ).length
                    } selected)</h3>
                  </div>
                  <p className="section-desc">
                    Select device (License Limit: {getMaxPdLimit()} PDs)
                  </p>
                  <div className="nd-scanner">
                    <table>
                      <thead>
                        <tr>
                          <th>
                            <input
                              type="checkbox"
                              checked={(config.NVME_LIST || []).length > 0 && (config.NVME_LIST || []).length === Math.min(systemInfo.nvme_info.length, getMaxPdLimit())}
                              onChange={handleSelectAllToggle}
                              title="Select All (respects license limit)"
                            />
                          </th>
                          <th>
                            Device
                            <SortButton columnKey="DevPath" currentConfig={nvmeSortConfig} />
                          </th>
                          <th>
                            Model
                            <SortButton columnKey="Model" currentConfig={nvmeSortConfig} />
                          </th>
                          <th>
                            Capacity
                            <SortButton columnKey="Capacity" currentConfig={nvmeSortConfig} />
                          </th>
                          <th>
                            NUMA
                            <SortButton columnKey="Numa" currentConfig={nvmeSortConfig} />
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedNvmeInfo.map((dev, idx) => (
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
                    Object.entries(config)
                      .filter(([key]) => !HIDDEN_PARAMS.includes(key))
                      .map(([key, val]) => [
                        key,
                        SENSITIVE_PARAMS.includes(key) ? '********' : val
                      ])
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
                    <div className={`status-box ${runStatus === 'NORMAL' ? 'status-normal' :
                      runStatus === 'REBUILD' ? 'status-rebuild' :
                        runStatus === 'DISCARD' ? 'status-discard' :
                          runStatus === 'PRECONDITIONING' ? 'status-precondition' :
                            runStatus === 'SUSTAINING' ? 'status-sustaining' :
                              'status-general-running'
                      }`}>
                      <div className="status-label">RUN STATUS</div>
                      <div className="status-value">
                        {runStatus}
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

              {benchmarkRunning && (
                <div className="progress-section">
                  <div className="progress-info">
                    <div className="progress-text">
                      <span>Total Progress: {progress.percentage}% ({progress.current_step}/{progress.total_steps})</span>
                    </div>
                    <div className="progress-time">
                      <span>Elapsed: {formatTime(progress.elapsed)}</span>
                      <span>Remaining: {formatTime(progress.remaining)}</span>
                    </div>
                  </div>
                  <div className="progress-bar-container">
                    <div
                      className="progress-bar-fill"
                      style={{ width: `${progress.percentage}%` }}
                    ></div>
                  </div>
                </div>
              )}
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
                <div className="section-header-row">
                  <h3>Real-time Monitor</h3>
                  <div className="dashboard-header-toggle">
                    <button
                      className={`view-toggle-btn ${!showAdvancedLog && activeViewMode === 'chart' ? 'active' : ''}`}
                      onClick={() => {
                        setShowAdvancedLog(false);
                        setActiveViewMode('chart');
                      }}
                    >
                      Chart View
                    </button>
                    <button
                      className={`view-toggle-btn ${!showAdvancedLog && activeViewMode === 'cdm' ? 'active' : ''}`}
                      onClick={() => {
                        setShowAdvancedLog(false);
                        setActiveViewMode('cdm');
                      }}
                    >
                      Report View
                    </button>
                    <button
                      className={`view-toggle-btn ${showAdvancedLog ? 'active' : ''}`}
                      onClick={() => setShowAdvancedLog(true)}
                    >
                      Audit Log
                    </button>
                  </div>
                </div>

                {showAdvancedLog && (
                  <div className="advanced-log-container">
                    <div className="section-header-row">
                      <h4 style={{ margin: '0 0 10px 0' }}>Audit Log</h4>
                    </div>
                    <pre className="log-viewer">
                      {advancedLogs.map((log, i) => (
                        <div key={i} className="log-line">{log}</div>
                      ))}
                      <div ref={logEndRef} />
                    </pre>
                  </div>
                )}

                {!showAdvancedLog && (
                  <RealTimeDashboard
                    data={realTimeData}
                    devices={Array.from(activeDevices)}
                    viewMode={activeViewMode}
                    setViewMode={setActiveViewMode}
                    testTarget={currentStage?.stage || null}
                  />
                )}
              </div>
            </div>
          )}



          {activeTab === 'calculator' && (
            <TheoreticalCalculator language={language} />
          )}

          {activeTab === 'results' && (
            <div className="results-panel">
              <h2>Test Results</h2>

              <div className="section-header-row" style={{ alignItems: 'center', gap: '15px' }}>
                <h3>Result Comparison</h3>
                <div className="selection-group" style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
                  <select
                    className="form-select"
                    onChange={(e) => handleResultSelect(e.target.value)}
                    value={selectedResults[0] || ''}
                    style={{ flex: 1, minWidth: '300px' }}
                  >
                    <option value="">-- Select Result --</option>
                    {results.sort((a, b) => b.name.localeCompare(a.name)).map((r, i) => (
                      <option key={i} value={r.name}>{r.name} ({r.created})</option>
                    ))}
                  </select>

                  <button
                    className="btn btn-primary"
                    onClick={loadComparisonData}
                    disabled={loadingResults || !selectedResults[0]}
                  >
                    {loadingResults ? 'Loading...' : '📊 Generate Comparison'}
                  </button>

                  {selectedResults[0] && (
                    <button
                      className="btn btn-success"
                      onClick={() => window.open(`${API_BASE_URL}/api/results/${selectedResults[0]}/download`, '_blank')}
                      title="Download full result archive (.tar)"
                    >
                      ⬇️ Download
                    </button>
                  )}
                </div>

                {comparisonData.graid && (
                  <button
                    className={`btn ${activeResultTab === 'gallery' ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => setActiveResultTab(activeResultTab === 'dashboard' ? 'gallery' : 'dashboard')}
                  >
                    {activeResultTab === 'gallery' ? '📊 Dashboard' : '🖼️ Gallery'}
                  </button>
                )}
              </div>

              {loadingResults && (
                <div className="loading-overlay">
                  <div className="loader"></div>
                  <p>Processing result data and images...</p>
                </div>
              )}

              {comparisonData.graid && !loadingResults && (
                <div className="result-view-container" style={{ marginTop: '20px' }}>
                  {activeResultTab === 'dashboard' ? (
                    <ComparisonDashboard
                      baselineData={comparisonData.baseline}
                      graidData={comparisonData.graid}
                      baselineMetadata={comparisonData.baselineMetadata}
                      graidMetadata={comparisonData.graidMetadata}
                    />
                  ) : (
                    <div className="report-gallery">
                      <div className="section-header-row" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: '20px' }}>
                        <div style={{ flex: 1 }}>
                          <h3>Report View Gallery</h3>
                          <div className="gallery-stats">
                            {reportImages.filter(img => {
                              const matchRaid = galleryFilters.raid === 'All' || img.tags.raid === galleryFilters.raid;
                              const matchStatus = galleryFilters.status === 'All' || img.tags.status === galleryFilters.status;
                              const matchType = galleryFilters.type === 'All' || img.tags.category === galleryFilters.type;
                              return matchRaid && matchStatus && matchType;
                            }).length} of {reportImages.length} images visible
                          </div>
                        </div>

                        <div className="gallery-filters" style={{ display: 'flex', gap: '10px', background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '8px' }}>
                          <div className="filter-group">
                            <label style={{ fontSize: '10px', display: 'block', color: '#888' }}>RAID</label>
                            <select
                              className="form-select"
                              style={{ fontSize: '12px', padding: '4px 8px' }}
                              value={galleryFilters.raid}
                              onChange={(e) => setGalleryFilters(prev => ({ ...prev, raid: e.target.value }))}
                            >
                              <option value="All">All RAID</option>
                              {Array.from(new Set(reportImages.map(img => img.tags.raid))).sort().map(r => <option key={r} value={r}>{r}</option>)}
                            </select>
                          </div>
                          <div className="filter-group">
                            <label style={{ fontSize: '10px', display: 'block', color: '#888' }}>STATUS</label>
                            <select
                              className="form-select"
                              style={{ fontSize: '12px', padding: '4px 8px' }}
                              value={galleryFilters.status}
                              onChange={(e) => setGalleryFilters(prev => ({ ...prev, status: e.target.value }))}
                            >
                              <option value="All">All Status</option>
                              {Array.from(new Set(reportImages.map(img => img.tags.status))).sort().map(s => <option key={s} value={s}>{s}</option>)}
                            </select>
                          </div>
                          <div className="filter-group">
                            <label style={{ fontSize: '10px', display: 'block', color: '#888' }}>TYPE</label>
                            <select
                              className="form-select"
                              style={{ fontSize: '12px', padding: '4px 8px' }}
                              value={galleryFilters.type}
                              onChange={(e) => setGalleryFilters(prev => ({ ...prev, type: e.target.value }))}
                            >
                              <option value="All">All Type</option>
                              <option value="VD">VD (SupremeRAID)</option>
                              <option value="PD">PD (Baseline)</option>
                            </select>
                          </div>
                        </div>
                      </div>

                      {reportImages.length === 0 ? (
                        <div className="empty-message" style={{ textAlign: 'center', padding: '40px' }}>
                          No report images found in this result.
                        </div>
                      ) : (
                        <div className="gallery-grid">
                          {reportImages.filter(img => {
                            const matchRaid = galleryFilters.raid === 'All' || img.tags.raid === galleryFilters.raid;
                            const matchStatus = galleryFilters.status === 'All' || img.tags.status === galleryFilters.status;
                            const matchType = galleryFilters.type === 'All' || img.tags.category === galleryFilters.type;
                            return matchRaid && matchStatus && matchType;
                          }).map((img, idx) => (
                            <div key={idx} className="gallery-item">
                              <img
                                src={`${API_BASE_URL}${img.url}`}
                                alt={img.name}
                                loading="lazy"
                                onClick={() => window.open(`${API_BASE_URL}${img.url}`, '_blank')}
                              />
                              <div className="image-tags">
                                <span className={`tag tag-cat tag-${img.tags.category.toLowerCase()}`}>{img.tags.category}</span>
                                <span className="tag tag-raid">{img.tags.raid}</span>
                                <span className="tag tag-status">{img.tags.status}</span>
                                <span className="tag tag-workload">{img.tags.workload}</span>
                                <span className="tag tag-bs">{img.tags.bs}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <footer className="app-footer">
        <p>SupremeRAID Benchmark Web GUI v1.0.0 | API: {API_BASE_URL}</p>
      </footer>

      {
        isResetting && (
          <div className="reset-overlay">
            <div className="reset-content">
              <div className="reset-spinner"></div>
              <h3>Resetting Graid Configuration</h3>
              <p>Please wait while existing resources (VDs, DGs, PDs) are being deleted...</p>
            </div>
          </div>
        )
      }
    </div >
  );
}

export default App;