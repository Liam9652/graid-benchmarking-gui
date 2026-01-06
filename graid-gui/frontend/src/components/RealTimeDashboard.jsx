import React from 'react';
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

const RealTimeDashboard = ({ data }) => {
    // data is expected to be an array of objects:
    // { timestamp: 'HH:mm:ss', iops_read: 0, iops_write: 0, bw_read: 0, bw_write: 0, lat_read: 0, lat_write: 0 }

    return (
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
                        <Line type="monotone" dataKey="iops_read" stroke="#8884d8" name="Read IOPS" dot={false} />
                        <Line type="monotone" dataKey="iops_write" stroke="#82ca9d" name="Write IOPS" dot={false} />
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
                        <Line type="monotone" dataKey="bw_read" stroke="#8884d8" name="Read BW" dot={false} />
                        <Line type="monotone" dataKey="bw_write" stroke="#82ca9d" name="Write BW" dot={false} />
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
                        <Line type="monotone" dataKey="lat_read" stroke="#8884d8" name="Read Lat" dot={false} />
                        <Line type="monotone" dataKey="lat_write" stroke="#82ca9d" name="Write Lat" dot={false} />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};

export default RealTimeDashboard;
