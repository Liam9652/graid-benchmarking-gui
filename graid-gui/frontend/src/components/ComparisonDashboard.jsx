import React from 'react';
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer
} from 'recharts';

const ComparisonDashboard = ({ baselineData, graidData }) => {
    // Prepare data for charts
    // Assuming data structure from parser CSVs

    const prepareChartData = () => {
        if (!baselineData || !graidData) return [];

        // Example aggregation logic - this depends heavily on the CSV structure
        // We'll assume we want to compare average IOPS/BW for specific block sizes/RW mixes

        // For now, let's create a dummy structure to visualize
        // In real implementation, we need to match rows by BlockSize/QueueDepth/etc.

        const combined = [];

        // This is a placeholder logic. Real logic needs to parse the full dataset.
        // We will iterate through baseline and find matching graid entry

        baselineData.forEach(bItem => {
            const gItem = graidData.find(g =>
                g.BlockSize === bItem.BlockSize &&
                g.Type === bItem.Type &&
                g['Queue Depth'] === bItem['Queue Depth']
            );

            if (gItem) {
                combined.push({
                    name: `${bItem.Type} ${bItem.BlockSize}`,
                    baseline_iops: parseFloat(bItem['IOPS(K)']),
                    graid_iops: parseFloat(gItem['IOPS(K)']),
                    baseline_bw: parseFloat(bItem['Bandwidth (GB/s)']),
                    graid_bw: parseFloat(gItem['Bandwidth (GB/s)']),
                });
            }
        });

        return combined;
    };

    const chartData = prepareChartData();

    if (chartData.length === 0) {
        return <div>Select two compatible result sets to compare.</div>;
    }

    return (
        <div className="dashboard-grid">
            <div className="chart-container">
                <h3>IOPS Comparison (K)</h3>
                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="name" />
                        <YAxis />
                        <Tooltip />
                        <Legend />
                        <Bar dataKey="baseline_iops" fill="#8884d8" name="Baseline" />
                        <Bar dataKey="graid_iops" fill="#82ca9d" name="Graid" />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            <div className="chart-container">
                <h3>Bandwidth Comparison (GB/s)</h3>
                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="name" />
                        <YAxis />
                        <Tooltip />
                        <Legend />
                        <Bar dataKey="baseline_bw" fill="#8884d8" name="Baseline" />
                        <Bar dataKey="graid_bw" fill="#82ca9d" name="Graid" />
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};

export default ComparisonDashboard;
