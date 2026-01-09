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
    LabelList,
    ReferenceLine
} from 'recharts';
import { calculatePerformance } from '../utils/perfCalculator';

const WORKLOADS_OF_INTEREST = [
    '4k Random Read',
    '4k Random Write',
    '1M Sequential Read',
    '1M Sequential Write'
];

const ComparisonDashboard = ({ baselineData, graidData, baselineMetadata, graidMetadata }) => {
    const [availableMetrics, setAvailableMetrics] = React.useState([]);
    const [availableWorkloads, setAvailableWorkloads] = React.useState([]);
    const [selectedMetrics, setSelectedMetrics] = React.useState(['IOPS(K)', 'Bandwidth (GB/s)']);
    const [selectedWorkloads, setSelectedWorkloads] = React.useState(WORKLOADS_OF_INTEREST);

    // BLUE COLOR SCALE for RAID bars
    const RAID_COLORS = ['#00BBED', '#00779E', '#33D1FF', '#004C66', '#B3F0FF'];
    const [availableRaidTypes, setAvailableRaidTypes] = React.useState([]);
    const [selectedRaidTypes, setSelectedRaidTypes] = React.useState([]);
    const [availableRaidStatuses, setAvailableRaidStatuses] = React.useState([]);
    const [selectedRaidStatuses, setSelectedRaidStatuses] = React.useState([]);
    const [availableStages, setAvailableStages] = React.useState([]);
    const [selectedStages, setSelectedStages] = React.useState([]);
    const [showBaseline, setShowBaseline] = React.useState(true);

    // Effect to extract available metrics and workloads from data
    React.useEffect(() => {
        if (!baselineData && !graidData) return;

        const allData = [...(baselineData || []), ...(graidData || [])];
        if (allData.length === 0) return;

        // Check availability in Graid data for conditional conditional display
        const graidWorkloads = new Set((graidData || []).map(d => d.Workload));

        // Extract Workloads (excluding SingleTest/Baseline as it will be in RAID types)
        const workloads = Array.from(new Set(allData.map(d => d.Workload)))
            .filter(Boolean)
            .filter(wl => {
                if (wl === 'SingleTest' || wl === 'Baseline') return false;
                // Hiding Logic:
                if (wl === '32k Sequential Read') return false;
                if (wl === '32.00 Sequential Read') return false;
                if (wl === '128.00 Sequential Read') return false;
                if (wl === '128.00 Sequential Write') return false;
                if (wl === '4k randrw') return false; // Hide default mixed (randrw55)

                // Conditional Logic:
                if (wl === '4k Random Read/Write Mix(70/30)') {
                    return graidWorkloads.has(wl);
                }

                return true;
            })
            .sort();

        setAvailableWorkloads(workloads);

        // Extract RAID Types (Only actual RAID levels from Graid data)
        const raidTypes = Array.from(new Set((graidData || [])
            .map(d => d.RAID_type)
            .filter(type => type && type !== 'SingleTest' && !type.includes('Baseline'))
        ));
        setAvailableRaidTypes(raidTypes.sort());
        setSelectedRaidTypes(raidTypes);

        // Check if Baseline (SingleTest) exists to enable the toggle
        const hasBaseline = allData.some(d => d.RAID_type === 'SingleTest' || d.Workload === 'SingleTest');
        if (!hasBaseline) setShowBaseline(false);
        else setShowBaseline(true);

        // Extract RAID Statuses from Graid data
        const raidStatuses = Array.from(new Set((graidData || []).map(d => d.RAID_status))).filter(Boolean);
        setAvailableRaidStatuses(raidStatuses.sort());
        if (selectedRaidStatuses.length === 0) setSelectedRaidStatuses(raidStatuses);

        // Extract Stages from Graid data
        const stages = Array.from(new Set((graidData || []).map(d => d.stage))).filter(Boolean);
        setAvailableStages(stages.sort());
        if (selectedStages.length === 0) setSelectedStages(stages);

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

    const handleRaidTypeToggle = (type) => {
        setSelectedRaidTypes(prev =>
            prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
        );
    };

    const handleRaidStatusToggle = (status) => {
        setSelectedRaidStatuses(prev =>
            prev.includes(status) ? prev.filter(s => s !== status) : [...prev, status]
        );
    };

    const handleStageToggle = (stage) => {
        setSelectedStages(prev =>
            prev.includes(stage) ? prev.filter(s => s !== stage) : [...prev, stage]
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
        if (!baselineData || !graidData) return [];

        const groups = [];

        // Determine all unique (stage, status) pairs in selected ranges
        const relevantEntries = (graidData || []).filter(d =>
            selectedStages.includes(d.stage) &&
            selectedRaidStatuses.includes(d.RAID_status)
        );

        // Sort keys to have consistent order: Normal first if multiple statuses, stages in alpha
        const groupKeys = Array.from(new Set(relevantEntries.map(d => `${d.stage}|${d.RAID_status}`))).sort((a, b) => {
            // Basic sort: Normal before Rebuild
            if (a.includes('Normal') && b.includes('Rebuild')) return -1;
            if (a.includes('Rebuild') && b.includes('Normal')) return 1;
            return a.localeCompare(b);
        });

        groupKeys.forEach(key => {
            const [stage, status] = key.split('|');
            const groupCharts = {};

            selectedWorkloads.forEach(workload => {
                const searchWl = workload === 'Baseline' ? 'SingleTest' : workload;

                const bItems = (baselineData || []).filter(d => d.Workload === searchWl);
                const bItem = bItems.reduce((prev, current) => {
                    const prevVal = parseFloat(prev['IOPS(K)'] || 0);
                    const currVal = parseFloat(current['IOPS(K)'] || 0);
                    return currVal > prevVal ? current : prev;
                }, {});

                const chartData = selectedMetrics.map(metric => {
                    const dataPoint = {
                        name: metric,
                        Baseline: showBaseline ? parseFloat(bItem[metric] || 0) : 0,
                    };

                    selectedRaidTypes.forEach(raidType => {
                        const item = (graidData || []).find(d =>
                            d.stage === stage &&
                            d.RAID_status === status &&
                            d.Workload === searchWl &&
                            d.RAID_type === raidType
                        );

                        if (item) {
                            dataPoint[`SupremeRAID - ${raidType}`] = parseFloat(item[metric] || 0);
                        }
                    });
                    return dataPoint;
                });
                groupCharts[workload] = chartData;
            });

            groups.push({ stage, status, charts: groupCharts });
        });

        return groups;
    };

    const resultGroups = prepareChartData();

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

                <div className="config-group">
                    <div className="checkbox-group" style={{ marginBottom: '10px' }}>
                        <label className="checkbox-item" style={{ fontWeight: 'bold', border: '1px solid #52C41A', padding: '5px 10px', borderRadius: '4px' }}>
                            <input
                                type="checkbox"
                                checked={showBaseline}
                                onChange={() => setShowBaseline(!showBaseline)}
                            />
                            Show Baseline (Single PD)
                        </label>
                    </div>

                    <strong>RAID Types: </strong>
                    <div className="checkbox-group">
                        {availableRaidTypes.map(type => (
                            <label key={type} className="checkbox-item">
                                <input
                                    type="checkbox"
                                    checked={selectedRaidTypes.includes(type)}
                                    onChange={() => handleRaidTypeToggle(type)}
                                /> {type}
                            </label>
                        ))}
                    </div>
                </div>

                <div style={{ marginBottom: '10px' }}>
                    <strong>Stages: </strong>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '5px' }}>
                        {availableStages.map(stage => (
                            <label key={stage} style={{ cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={selectedStages.includes(stage)}
                                    onChange={() => handleStageToggle(stage)}
                                /> {stage.replace('after', '').toUpperCase()}
                            </label>
                        ))}
                    </div>
                </div>

                <div style={{ marginBottom: '10px' }}>
                    <strong>RAID Statuses: </strong>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '5px' }}>
                        {availableRaidStatuses.map(status => (
                            <label key={status} style={{ cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={selectedRaidStatuses.includes(status)}
                                    onChange={() => handleRaidStatusToggle(status)}
                                /> {status}
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
            <div className="result-groups-container">
                {resultGroups.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '40px' }}>
                        No data found for selected Stage/Status/RAID filters.
                    </div>
                ) : (
                    resultGroups.map((group, groupIdx) => (
                        <div key={groupIdx} className="result-group-section" style={{ marginBottom: '40px', borderTop: '2px solid #34495e', paddingTop: '20px' }}>
                            <h2 style={{ color: '#00BBED', marginBottom: '20px' }}>
                                Stage: <span style={{ color: '#fff' }}>{group.stage.replace('after', '').toUpperCase()}</span> |
                                Status: <span style={{ color: group.status === 'Normal' ? '#52C41A' : '#f1c40f' }}>{group.status}</span>
                            </h2>

                            <div className="dashboard-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
                                {selectedWorkloads.filter(w => w !== 'Baseline').map(workload => {
                                    const data = group.charts[workload];
                                    if (!data || data.length === 0) return null;

                                    // Check if any bar (Baseline or SupremeRAID) has data
                                    const hasAnyData = data.some(d => d.Baseline > 0 || Object.keys(d).some(k => k.startsWith('SupremeRAID') && d[k] > 0));
                                    if (!hasAnyData) return null;

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
                                                    {data[0]?.Baseline > 0 && group.status !== 'Rebuild' && (
                                                        <Bar dataKey="Baseline" fill="#52C41A">
                                                            <LabelList dataKey="Baseline" content={<CustomBarLabel />} />
                                                        </Bar>
                                                    )}
                                                    {selectedRaidTypes.map((type, idx) => {
                                                        const dataKey = `SupremeRAID - ${type}`;
                                                        if (!data.some(d => d[dataKey] > 0)) return null;

                                                        return (
                                                            <Bar key={type} dataKey={dataKey} fill={RAID_COLORS[idx % RAID_COLORS.length]}>
                                                                <LabelList dataKey={dataKey} content={<CustomBarLabel />} />
                                                            </Bar>
                                                        );
                                                    })}
                                                </BarChart>
                                            </ResponsiveContainer>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default ComparisonDashboard;
