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
    const [availableMetrics, setAvailableMetrics] = React.useState([]);
    const [availableWorkloads, setAvailableWorkloads] = React.useState([]);
    const [selectedMetrics, setSelectedMetrics] = React.useState(['IOPS(K)', 'Bandwidth (GB/s)']);
    const [selectedWorkloads, setSelectedWorkloads] = React.useState(WORKLOADS_OF_INTEREST);

    // Effect to extract available metrics and workloads from data
    React.useEffect(() => {
        if (!baselineData && !graidData) return;

        const allData = [...(baselineData || []), ...(graidData || [])];
        if (allData.length === 0) return;

        // Check availability in Graid data for conditional conditional display
        const graidWorkloads = new Set((graidData || []).map(d => d.Workload));

        // Extract Workloads
        const workloads = Array.from(new Set(allData.map(d => d.Workload)))
            .filter(Boolean)
            .filter(wl => {
                // Hiding Logic:
                if (wl === '32k Sequential Read') return false;
                if (wl === '32.00 Sequential Read') return false;
                if (wl === '4k randrw') return false; // Hide default mixed (randrw55)

                // Conditional Logic:
                // If it is regular mixed (70/30), check if Graid has it
                if (wl === '4k Random Read/Write Mix(70/30)') {
                    // Only show if Graid data has this workload
                    return graidWorkloads.has(wl);
                }

                return true;
            })
            .sort();
        setAvailableWorkloads(workloads);
        // Default select all standard ones if present, or all if none standard found
        // actually keep default to standard interest list, but allow expanding

        // Extract Numeric Metrics
        const sample = allData[0];
        const metrics = Object.keys(sample).filter(key => {
            // Filter out non-numeric/metadata keys
            const ignored = ['filename', 'Workload', 'Type', 'Model', 'Ben_type', 'RAID_status', 'RAID_type', 'stage', 'SSD', 'controller', 'fio-version'];
            if (ignored.includes(key)) return false;

            // User requested filters: hide percentiles (endswith th), PD_count, Unnamed
            if (key.endsWith('th')) return false;
            if (key.includes('PD_count')) return false;
            if (key.includes('Unnamed')) return false;

            // Check if looks numeric (parseable)
            const val = parseFloat(sample[key]);
            return !isNaN(val);
        });
        setAvailableMetrics(metrics.sort());

    }, [baselineData, graidData]);

    const handleMetricToggle = (metric) => {
        setSelectedMetrics(prev =>
            prev.includes(metric) ? prev.filter(m => m !== metric) : [...prev, metric]
        );
    };

    const handleWorkloadToggle = (workload) => {
        setSelectedWorkloads(prev =>
            prev.includes(workload) ? prev.filter(w => w !== workload) : [...prev, workload]
        );
    };

    // ... CustomBarLabel ...
    const CustomBarLabel = (props) => {
        const { x, y, width, value } = props;
        return (
            <text x={x + width / 2} y={y - 5} fill="#fff" textAnchor="middle" fontSize={12} fontWeight="bold">
                {value}
            </text>
        );
    };

    const prepareChartData = () => {
        if (!baselineData || !graidData) return {};

        const groupedData = {};

        // Use selectedWorkloads instead of static list
        selectedWorkloads.forEach(workload => {
            const bItems = baselineData.filter(d => d.Workload === workload);
            const gItems = graidData.filter(d => d.Workload === workload);

            // Reducers to find best item (max IOPS logic still valid as default proxy for "best result")
            // Or strictly max of the FIRST selected metric?
            // Let's stick to simple assumption: usually one result per workload in summary.
            // If multiple, verify logic implies taking the one with highest IOPS is a good "Best run" heuristic.
            const bItem = bItems.reduce((prev, current) => {
                const prevVal = parseFloat(prev['IOPS(K)'] || 0);
                const currVal = parseFloat(current['IOPS(K)'] || 0);
                return currVal > prevVal ? current : prev;
            }, {});
            const gItem = gItems.reduce((prev, current) => {
                const prevVal = parseFloat(prev['IOPS(K)'] || 0);
                const currVal = parseFloat(current['IOPS(K)'] || 0);
                return currVal > prevVal ? current : prev;
            }, {});

            if (bItems.length > 0 || gItems.length > 0) {
                // Map selected metrics to chart data
                groupedData[workload] = selectedMetrics.map(metric => ({
                    name: metric,
                    Baseline: parseFloat(bItem[metric] || 0),
                    SupremeRAID: parseFloat(gItem[metric] || 0) // Changed Graid -> SupremeRAID
                }));
            }
        });

        return groupedData;
    };

    const chartsData = prepareChartData();

    return (
        <div>
            {/* Configuration Panel */}
            <div style={{ padding: '15px', marginBottom: '20px', borderRadius: '8px' }}>
                <h4 style={{ marginTop: 0 }}>Comparison Config</h4>

                <div style={{ marginBottom: '10px' }}>
                    <strong>Workloads: </strong>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '5px' }}>
                        {availableWorkloads.map(wl => (
                            <label key={wl} style={{ cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={selectedWorkloads.includes(wl)}
                                    onChange={() => handleWorkloadToggle(wl)}
                                /> {wl}
                            </label>
                        ))}
                    </div>
                </div>

                <div>
                    <strong>Metrics: </strong>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '5px' }}>
                        {availableMetrics.map(m => (
                            <label key={m} style={{ cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={selectedMetrics.includes(m)}
                                    onChange={() => handleMetricToggle(m)}
                                /> {m}
                            </label>
                        ))}
                    </div>
                </div>
            </div>

            {/* Charts Grid */}
            <div className="dashboard-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
                {Object.keys(chartsData).length === 0 ? (
                    <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '20px' }}>
                        No data or no selection matches.
                    </div>
                ) : (
                    selectedWorkloads.map(workload => {
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
                                        <Bar dataKey="Baseline" fill="#52C41A">
                                            <LabelList dataKey="Baseline" content={<CustomBarLabel />} />
                                        </Bar>
                                        <Bar dataKey="SupremeRAID" fill="#00BBED">
                                            <LabelList dataKey="SupremeRAID" content={<CustomBarLabel />} />
                                        </Bar>
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
};

export default ComparisonDashboard;
