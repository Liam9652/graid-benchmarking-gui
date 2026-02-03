import React, { useState } from 'react';
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer
} from 'recharts';

const COLORS = [
    '#8884d8', '#82ca9d', '#ffc658', '#ff8042', '#a4de6c',
    '#d0ed57', '#00C49F', '#0088FE', '#FFBB28', '#FF8042',
    '#3366cc', '#dc3912', '#ff9900', '#109618', '#990099',
    '#0099c6', '#dd4477', '#66aa00', '#b82e2e', '#316395'
];

const RealTimeDashboard = ({ data, devices = [], viewMode, setViewMode, testTarget = null }) => {
    const [visibleDevices, setVisibleDevices] = useState(new Set());
    const [showAll, setShowAll] = useState(false);

    // Filter devices based on test target
    const filterDevicesByTarget = (deviceList, target) => {
        if (!target) return deviceList;

        return deviceList.filter(dev => {
            if (target === 'PD') {
                // PD test: show only nvmeXn1 devices
                return /^nvme\d+n1$/.test(dev);
            } else if (target === 'VD') {
                // VD test: show gdgXnY or gdgX (no gvo)
                // Relaxed regex to include optional namespace
                return /^gdg\d+(n\d+)?$/.test(dev);
            } else if (target === 'MD') {
                // MD test: show only mdX devices
                return /^md\d+$/.test(dev);
            }
            return true;
        });
    };

    // Get filtered device list based on test target
    const filteredDevices = filterDevicesByTarget(devices, testTarget);

    // Update visible devices when devices prop changes
    React.useEffect(() => {
        if (filteredDevices.length > 0 && visibleDevices.size === 0) {
            // Default to showing first 8 devices if not "showAll"
            const initial = new Set(filteredDevices.slice(0, 8));
            setVisibleDevices(initial);
        }
    }, [filteredDevices]);

    const activeList = showAll ? filteredDevices : filteredDevices.filter(d => visibleDevices.has(d));
    // data structure: { timestamp, "dev1_iops_read": ..., "dev2_iops_read": ... }

    // Fallback if no devices detected yet (or single device mode implicit)
    // Actually, App.jsx passes devices now. If empty, maybe show nothing or wait.

    // const [viewMode, setViewMode] = useState('chart'); // Lifted to App.jsx

    // Calculate aggregates for CDM view
    const latest = data && data.length > 0 ? data[data.length - 1] : null;
    let totalReadBW = 0, totalWriteBW = 0;
    let totalReadIOPS = 0, totalWriteIOPS = 0;
    let avgReadLat = 0, avgWriteLat = 0;
    let devCount = 0;

    if (latest && filteredDevices.length > 0) {
        filteredDevices.forEach(dev => {
            if (latest[`${dev}_iops_read`] !== undefined) {
                totalReadIOPS += latest[`${dev}_iops_read`] || 0;
                totalWriteIOPS += latest[`${dev}_iops_write`] || 0;
                totalReadBW += latest[`${dev}_bw_read`] || 0;
                totalWriteBW += latest[`${dev}_bw_write`] || 0;
                avgReadLat += latest[`${dev}_lat_read`] || 0;
                avgWriteLat += latest[`${dev}_lat_write`] || 0;
                devCount++;
            }
        });
        if (devCount > 0) {
            avgReadLat /= devCount;
            avgWriteLat /= devCount;
        }
    }

    // Helper functions for unit formatting
    const formatThroughput = (val) => {
        if (val >= 1000) {
            return { value: (val / 1000).toFixed(2), unit: 'GB/s' };
        }
        return { value: val.toFixed(2), unit: 'MB/s' };
    };

    const formatIOPS = (val) => {
        if (val >= 1000000) {
            return { value: (val / 1000000).toFixed(2), unit: 'MIO/s' };
        }
        if (val >= 1000) {
            return { value: (val / 1000).toFixed(2), unit: 'KIO/s' };
        }
        return { value: val.toFixed(0), unit: 'IO/s' };
    };

    const formatLatency = (val) => {
        if (val === 0) return { value: '0.000', unit: 'ms' };
        if (val < 0.001) {
            return { value: (val * 1000000).toFixed(2), unit: 'ns' };
        }
        if (val < 1) {
            return { value: (val * 1000).toFixed(2), unit: 'us' };
        }
        return { value: val.toFixed(3), unit: 'ms' };
    };

    const readBWDisplay = formatThroughput(totalReadBW);
    const writeBWDisplay = formatThroughput(totalWriteBW);
    const readIOPSDisplay = formatIOPS(totalReadIOPS);
    const writeIOPSDisplay = formatIOPS(totalWriteIOPS);
    const readLatDisplay = formatLatency(avgReadLat);
    const writeLatDisplay = formatLatency(avgWriteLat);

    return (
        <div className="dashboard-wrapper" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="filter-card" style={{
                background: '#f8f9fa',
                padding: '15px',
                borderRadius: '8px',
                border: '1px solid #dee2e6',
                boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
            }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <h4 style={{ margin: 0 }}>Device Monitor Filter ({activeList.length}/{filteredDevices.length} active){testTarget && ` [${testTarget} Mode]`}</h4>
                    <button
                        className={`btn-filter ${showAll ? 'active' : ''}`}
                        onClick={() => setShowAll(!showAll)}
                        style={{
                            padding: '6px 12px',
                            fontSize: '13px',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            background: showAll ? '#007bff' : '#fff',
                            color: showAll ? '#fff' : '#007bff',
                            border: '1px solid #007bff'
                        }}
                    >
                        {showAll ? 'Show Manual Selection' : 'Monitor All Devices'}
                    </button>
                </div>

                <div style={{
                    maxHeight: '80px',
                    overflowY: 'auto',
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: '8px',
                    padding: '8px',
                    background: '#fff',
                    borderRadius: '4px',
                    border: '1px solid #e9ecef'
                }}>
                    {filteredDevices.map(dev => (
                        <label key={dev} style={{
                            fontSize: '12px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            cursor: 'pointer',
                            padding: '2px 8px',
                            background: visibleDevices.has(dev) || showAll ? '#e7f3ff' : '#f8f9fa',
                            borderRadius: '12px',
                            border: '1px solid',
                            borderColor: visibleDevices.has(dev) || showAll ? '#b6d4fe' : '#dee2e6'
                        }}>
                            <input
                                type="checkbox"
                                checked={showAll || visibleDevices.has(dev)}
                                disabled={showAll}
                                onChange={() => {
                                    const next = new Set(visibleDevices);
                                    if (next.has(dev)) next.delete(dev);
                                    else next.add(dev);
                                    setVisibleDevices(next);
                                }}
                            />
                            {dev}
                        </label>
                    ))}
                </div>
            </div>

            {viewMode === 'chart' ? (
                <div className="dashboard-grid" style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))',
                    gap: '20px'
                }}>
                    <div className="chart-container" style={{ background: '#fff', padding: '15px', borderRadius: '8px', border: '1px solid #dee2e6' }}>
                        <h3 style={{ marginTop: 0, marginBottom: '15px', fontSize: '16px' }}>IOPS (IO/s)</h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                <XAxis dataKey="timestamp" hide={true} />
                                <YAxis fontSize={12} />
                                <Tooltip />
                                <Legend
                                    layout="horizontal"
                                    verticalAlign="bottom"
                                    align="center"
                                    wrapperStyle={{ paddingTop: '20px', maxHeight: '100px', overflowY: 'auto' }}
                                />
                                {activeList.map((dev, idx) => (
                                    <React.Fragment key={dev}>
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_iops_read`}
                                            stroke={COLORS[(idx * 2) % COLORS.length]}
                                            name={`${dev} R`}
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={1.5}
                                        />
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_iops_write`}
                                            stroke={COLORS[(idx * 2 + 1) % COLORS.length]}
                                            name={`${dev} W`}
                                            strokeDasharray="5 5"
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={1.5}
                                        />
                                    </React.Fragment>
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="chart-container" style={{ background: '#fff', padding: '15px', borderRadius: '8px', border: '1px solid #dee2e6' }}>
                        <h3 style={{ marginTop: 0, marginBottom: '15px', fontSize: '16px' }}>Bandwidth (MB/s)</h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                <XAxis dataKey="timestamp" hide={true} />
                                <YAxis fontSize={12} />
                                <Tooltip />
                                <Legend
                                    layout="horizontal"
                                    verticalAlign="bottom"
                                    align="center"
                                    wrapperStyle={{ paddingTop: '20px', maxHeight: '100px', overflowY: 'auto' }}
                                />
                                {activeList.map((dev, idx) => (
                                    <React.Fragment key={dev}>
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_bw_read`}
                                            stroke={COLORS[(idx * 2) % COLORS.length]}
                                            name={`${dev} RBW`}
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={1.5}
                                        />
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_bw_write`}
                                            stroke={COLORS[(idx * 2 + 1) % COLORS.length]}
                                            name={`${dev} WBW`}
                                            strokeDasharray="5 5"
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={1.5}
                                        />
                                    </React.Fragment>
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="chart-container" style={{ background: '#fff', padding: '15px', borderRadius: '8px', border: '1px solid #dee2e6' }}>
                        <h3 style={{ marginTop: 0, marginBottom: '15px', fontSize: '16px' }}>Latency (ms)</h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                <XAxis dataKey="timestamp" hide={true} />
                                <YAxis fontSize={12} />
                                <Tooltip />
                                <Legend
                                    layout="horizontal"
                                    verticalAlign="bottom"
                                    align="center"
                                    wrapperStyle={{ paddingTop: '20px', maxHeight: '100px', overflowY: 'auto' }}
                                />
                                {activeList.map((dev, idx) => (
                                    <React.Fragment key={dev}>
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_lat_read`}
                                            stroke={COLORS[(idx * 2) % COLORS.length]}
                                            name={`${dev} RLat`}
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={1.5}
                                        />
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_lat_write`}
                                            stroke={COLORS[(idx * 2 + 1) % COLORS.length]}
                                            name={`${dev} WLat`}
                                            strokeDasharray="5 5"
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={1.5}
                                        />
                                    </React.Fragment>
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            ) : (
                <div className="cdm-grid" style={{
                    display: 'grid',
                    gridTemplateColumns: '150px 1fr 1fr',
                    gap: '10px',
                    maxWidth: '1000px',
                    margin: '0 auto',
                    background: '#fff',
                    padding: '20px',
                    borderRadius: '12px',
                    boxShadow: '0 4px 15px rgba(0,0,0,0.05)'
                }}>
                    {/* Header Row */}
                    <div className="cdm-header-cell" style={{ visibility: 'hidden' }}>Metric</div>
                    <div className="cdm-cell value-cell-header read-header" style={{ width: '100%', minWidth: 'auto', textAlign: 'center', alignItems: 'center' }}>READ</div>
                    <div className="cdm-cell value-cell-header write-header" style={{ width: '100%', minWidth: 'auto', textAlign: 'center', alignItems: 'center' }}>WRITE</div>

                    {/* Throughput Row */}
                    <div className="cdm-cell label-cell" style={{ minHeight: '80px', height: '100%', minWidth: 'auto' }}>THROUGHPUT</div>
                    <div className="cdm-cell value-cell" style={{ minHeight: '80px', minWidth: 'auto' }}>
                        <span className="unit-label">{readBWDisplay.unit}</span>
                        {readBWDisplay.value}
                    </div>
                    <div className="cdm-cell value-cell" style={{ minHeight: '80px', minWidth: 'auto' }}>
                        <span className="unit-label">{writeBWDisplay.unit}</span>
                        {writeBWDisplay.value}
                    </div>

                    {/* IOPS Row */}
                    <div className="cdm-cell label-cell" style={{ minHeight: '80px', height: '100%', minWidth: 'auto' }}>IOPS</div>
                    <div className="cdm-cell value-cell" style={{ minHeight: '80px', minWidth: 'auto' }}>
                        <span className="unit-label">{readIOPSDisplay.unit}</span>
                        {readIOPSDisplay.value}
                    </div>
                    <div className="cdm-cell value-cell" style={{ minHeight: '80px', minWidth: 'auto' }}>
                        <span className="unit-label">{writeIOPSDisplay.unit}</span>
                        {writeIOPSDisplay.value}
                    </div>

                    {/* Latency Row */}
                    <div className="cdm-cell label-cell" style={{ minHeight: '80px', height: '100%', minWidth: 'auto' }}>LATENCY</div>
                    <div className="cdm-cell value-cell" style={{ minHeight: '80px', minWidth: 'auto' }}>
                        <span className="unit-label">{readLatDisplay.unit}</span>
                        {readLatDisplay.value}
                    </div>
                    <div className="cdm-cell value-cell" style={{ minHeight: '80px', minWidth: 'auto' }}>
                        <span className="unit-label">{writeLatDisplay.unit}</span>
                        {writeLatDisplay.value}
                    </div>
                </div>
            )}
        </div>
    );
};

export default RealTimeDashboard;
