import React from 'react';
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer,
    LabelList
} from 'recharts';

const WORKLOADS_OF_INTEREST = [
    '4k Random Read',
    '4k Random Write',
    '1M Sequential Read',
    '1M Sequential Write'
];

const ComparisonDashboard = ({ baselineData, graidData }) => {

    // Custom label component for BarChart
    const CustomBarLabel = (props) => {
        const { x, y, width, value } = props;
        return (
            <text x={x + width / 2} y={y - 5} fill="#fff" textAnchor="middle" fontSize={12}>
                {value}
            </text>
        );
    };

    const prepareChartData = () => {
        if (!baselineData || !graidData) return {};

        const groupedData = {};

        WORKLOADS_OF_INTEREST.forEach(workload => {
            // Find rows matching this workload
            // Note: We might have multiple rows (different QD/BS?), but usually these specific names imply a specific test.
            // If multiple QDs exist, we might need to average or pick one. Assuming single result per workload for now based on user request "show result".

            const bItems = baselineData.filter(d => d.Workload === workload);
            const gItems = graidData.filter(d => d.Workload === workload);

            // If we have data, we assume the user wants IOPS/BW comparison.
            // Let's take the MAX value if multiple exist as a simplified "best effort" or just the first one.
            // Or if it's a list (qd1, qd2...), we could show them all?
            // "Column chart" -> usually implies single comparison per workload.
            // Let's assume we want to compare the specific metric.

            // Heuristic search for best value
            const bItem = bItems.reduce((prev, current) => {
                const prevVal = parseFloat(prev['Read IOPS'] || prev['Write IOPS'] || 0);
                const currVal = parseFloat(current['Read IOPS'] || current['Write IOPS'] || 0);
                return currVal > prevVal ? current : prev;
            }, {});
            const gItem = gItems.reduce((prev, current) => {
                const prevVal = parseFloat(prev['Read IOPS'] || prev['Write IOPS'] || 0);
                const currVal = parseFloat(current['Read IOPS'] || current['Write IOPS'] || 0);
                return currVal > prevVal ? current : prev;
            }, {});

            let iopsKey = 'Read IOPS';
            let bwKey = 'Read BW';
            if (workload.includes('Write')) {
                iopsKey = 'Write IOPS';
                bwKey = 'Write BW';
            }

            if (bItems.length > 0 || gItems.length > 0) {
                groupedData[workload] = [
                    {
                        name: 'IOPS',
                        Baseline: parseFloat(bItem[iopsKey] || 0),
                        Graid: parseFloat(gItem[iopsKey] || 0)
                    },
                    {
                        name: 'Bandwidth (MB/s)',
                        Baseline: parseFloat(bItem[bwKey] || 0),
                        Graid: parseFloat(gItem[bwKey] || 0)
                    }
                ];
            }
        });

        return groupedData;
    };

    const chartsData = prepareChartData();

    if (Object.keys(chartsData).length === 0) {
        return (
            <div className="dashboard-grid">
                <div style={{ padding: '20px', textAlign: 'center', width: '100%' }}>
                    Waiting for data or no matching workloads found.
                    <br />
                    <small>Ensure your test names include standard patterns (e.g. 00-randread, 01-seqread)</small>
                </div>
            </div>
        );
    }

    return (
        <div className="dashboard-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
            {WORKLOADS_OF_INTEREST.map(workload => {
                const data = chartsData[workload];
                if (!data) return null;

                return (
                    <div className="chart-container" key={workload} style={{ minHeight: '350px' }}>
                        <h3>{workload}</h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" />
                                <YAxis />
                                <Tooltip cursor={{ fill: 'transparent' }} />
                                <Legend />
                                <Bar dataKey="Baseline" fill="#8884d8">
                                    <LabelList dataKey="Baseline" content={<CustomBarLabel />} />
                                </Bar>
                                <Bar dataKey="Graid" fill="#82ca9d">
                                    <LabelList dataKey="Graid" content={<CustomBarLabel />} />
                                </Bar>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                );
            })}
        </div>
    );
};

export default ComparisonDashboard;
