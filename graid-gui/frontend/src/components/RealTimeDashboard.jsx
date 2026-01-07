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
    '#d0ed57', '#00C49F', '#0088FE', '#FFBB28', '#FF8042'
];

const RealTimeDashboard = ({ data, devices = [], viewMode, setViewMode }) => {
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

    if (latest && devices.length > 0) {
        devices.forEach(dev => {
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
        <div className="dashboard-wrapper">
            <div className="dashboard-header-toggle">
                <button
                    className={`view-toggle-btn ${viewMode === 'chart' ? 'active' : ''}`}
                    onClick={() => setViewMode('chart')}
                >
                    Chart View
                </button>
                <button
                    className={`view-toggle-btn ${viewMode === 'cdm' ? 'active' : ''}`}
                    onClick={() => setViewMode('cdm')}
                >
                    Report View
                </button>
            </div>

            {viewMode === 'chart' ? (
                <div className="dashboard-grid">
                    <div className="chart-container">
                        <h3>IOPS (IO/s)</h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={data}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="timestamp" />
                                <YAxis />
                                <Tooltip />
                                <Legend />
                                {devices.map((dev, idx) => (
                                    <React.Fragment key={dev}>
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_iops_read`}
                                            stroke={COLORS[(idx * 2) % COLORS.length]}
                                            name={`${dev} Read`}
                                            dot={false}
                                        />
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_iops_write`}
                                            stroke={COLORS[(idx * 2 + 1) % COLORS.length]}
                                            name={`${dev} Write`}
                                            dot={false}
                                        />
                                    </React.Fragment>
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="chart-container">
                        <h3>Bandwidth (MB/s)</h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={data}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="timestamp" />
                                <YAxis />
                                <Tooltip />
                                <Legend />
                                {devices.map((dev, idx) => (
                                    <React.Fragment key={dev}>
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_bw_read`}
                                            stroke={COLORS[(idx * 2) % COLORS.length]}
                                            name={`${dev} Read BW`}
                                            dot={false}
                                        />
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_bw_write`}
                                            stroke={COLORS[(idx * 2 + 1) % COLORS.length]}
                                            name={`${dev} Write BW`}
                                            dot={false}
                                        />
                                    </React.Fragment>
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="chart-container">
                        <h3>Latency (ms)</h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={data}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="timestamp" />
                                <YAxis />
                                <Tooltip />
                                <Legend />
                                {devices.map((dev, idx) => (
                                    <React.Fragment key={dev}>
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_lat_read`}
                                            stroke={COLORS[(idx * 2) % COLORS.length]}
                                            name={`${dev} Read Lat`}
                                            dot={false}
                                        />
                                        <Line
                                            type="monotone"
                                            dataKey={`${dev}_lat_write`}
                                            stroke={COLORS[(idx * 2 + 1) % COLORS.length]}
                                            name={`${dev} Write Lat`}
                                            dot={false}
                                        />
                                    </React.Fragment>
                                ))}
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            ) : (
                <div className="cdm-grid">
                    <div className="cdm-row header-row">
                        <div className="cdm-cell label-cell">Metric</div>
                        <div className="cdm-cell value-cell-header read-header">READ</div>
                        <div className="cdm-cell value-cell-header write-header">WRITE</div>
                    </div>
                    <div className="cdm-row">
                        <div className="cdm-cell label-cell">THROUGHPUT</div>
                        <div className="cdm-cell value-cell">
                            <span className="unit-label">{readBWDisplay.unit}</span>
                            {readBWDisplay.value}
                        </div>
                        <div className="cdm-cell value-cell">
                            <span className="unit-label">{writeBWDisplay.unit}</span>
                            {writeBWDisplay.value}
                        </div>
                    </div>
                    <div className="cdm-row">
                        <div className="cdm-cell label-cell">IOPS</div>
                        <div className="cdm-cell value-cell">
                            <span className="unit-label">{readIOPSDisplay.unit}</span>
                            {readIOPSDisplay.value}
                        </div>
                        <div className="cdm-cell value-cell">
                            <span className="unit-label">{writeIOPSDisplay.unit}</span>
                            {writeIOPSDisplay.value}
                        </div>
                    </div>
                    <div className="cdm-row">
                        <div className="cdm-cell label-cell">LATENCY</div>
                        <div className="cdm-cell value-cell">
                            <span className="unit-label">{readLatDisplay.unit}</span>
                            {readLatDisplay.value}
                        </div>
                        <div className="cdm-cell value-cell">
                            <span className="unit-label">{writeLatDisplay.unit}</span>
                            {writeLatDisplay.value}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default RealTimeDashboard;
