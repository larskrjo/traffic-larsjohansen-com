import { useState } from "react";
import Grid from "@mui/material/Grid";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { ResponsiveHeatMap } from "@nivo/heatmap";

type HeatmapData = {
    [route: string]: {
        period: string;
        date_range: string;
        heatmap_data: {
            [day: string]: {
                [time: string]: number;
            };
        };
        weekdays: string[];
        times: string[];
    };
};

type HeatmapDataPoint = {
    x: string;
    y: number;
};

type HeatmapRow = {
    id: string;
    data: HeatmapDataPoint[];
};

function transformHeatmapData(routeData: HeatmapData[string]): HeatmapRow[] {
    const { heatmap_data, weekdays, times } = routeData;
    
    return weekdays.map((day) => ({
        id: day,
        data: times.map((time) => ({
            x: time,
            y: heatmap_data[day]?.[time] ?? 0,
        })),
    }));
}

function calculateMinMax(routeData: HeatmapData[string]): { min: number; max: number } {
    const { heatmap_data } = routeData;
    let min = Number.MAX_SAFE_INTEGER;
    let max = Number.MIN_SAFE_INTEGER;

    Object.values(heatmap_data).forEach((dayData) => {
        Object.values(dayData).forEach((value) => {
            min = Math.min(min, value);
            max = Math.max(max, value);
        });
    });

    return { min, max };
}

function formatMinutesToHours(minutes: number): string {
    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);
    
    if (hours === 0) {
        return `${mins}min`;
    }
    if (mins === 0) {
        return `${hours}h`;
    }
    return `${hours}h\n${mins}min`;
}

export default function HeatMap(props: { heatmapData: HeatmapData | null }) {
    const [selectedRoute, setSelectedRoute] = useState<string>("Home → Work");

    if (!props.heatmapData) {
        return (
            <Box sx={{ p: 3 }}>
                <Typography>Loading heatmap data...</Typography>
            </Box>
        );
    }

    const routes = Object.keys(props.heatmapData);
    const currentRouteData = props.heatmapData[selectedRoute];
    
    if (!currentRouteData) {
        return (
            <Box sx={{ p: 3 }}>
                <Typography>No data available for selected route.</Typography>
            </Box>
        );
    }

    const heatmapRows = transformHeatmapData(currentRouteData);
    const { min, max } = calculateMinMax(currentRouteData);
    const numTimes = currentRouteData.times.length;

    const handleRouteChange = (_event: React.SyntheticEvent, newValue: string) => {
        setSelectedRoute(newValue);
    };

    return (
        <Box sx={{ width: "100%", p: 2 }}>
            <Grid container spacing={2}>
                <Grid size={{ xs: 12 }}>
                    <Tabs value={selectedRoute} onChange={handleRouteChange} sx={{ mb: 2 }}>
                        {routes.map((route) => (
                            <Tab
                                key={route}
                                label={`${route} (${props.heatmapData![route].period})`}
                                value={route}
                            />
                        ))}
                    </Tabs>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                        {currentRouteData.date_range}
                    </Typography>
                </Grid>
                <Grid size={{ xs: 12 }}>
                    <Box sx={{ width: "100%", height: 600 }}>
                        <ResponsiveHeatMap
                            data={heatmapRows}
                            margin={{ top: -100, right: 90, bottom: 60, left:0 }}
                            valueFormat={(value) => formatMinutesToHours(value)}
                            axisTop={null}
                            xOuterPadding={0.5}
                            yOuterPadding={0.5}
                            xInnerPadding={0}
                            yInnerPadding={0}
                            axisRight={null}
                            axisLeft={{
                                tickSize: 5,
                                tickPadding: 3,
                                tickRotation: 0,
                                renderTick: (tick) => {
                                    return (
                                        <g transform={`translate(${tick.x}, ${tick.y})`}>

                                            <text
                                                x={10}
                                                y={45}
                                                textAnchor="start"
                                                dominantBaseline="middle"
                                                style={{
                                                    fill: '#454545',
                                                    fontSize: 12,
                                                }}
                                            >
                                                {tick.value}
                                            </text>
                                        </g>
                                    );
                                },
                            }}
                            axisBottom={{
                                tickSize: 5,
                                tickPadding: 5,
                                tickRotation: -90,
                                legend: "Time",
                                legendPosition: "middle",
                                legendOffset: 72,
                                renderTick: (tick) => {
                                    // Calculate cell width to center labels in the middle of each box
                                    const availableWidth = 600 - 90; // total width minus right margin
                                    const cellWidth = numTimes > 0 ? availableWidth / numTimes : 0;
                                    const offset = cellWidth / 2;
                                    return (
                                        <g transform={`translate(${tick.x + offset}, ${tick.y})`}>
                                            <text
                                                x={-20}
                                                y={15}
                                                textAnchor="middle"
                                                dominantBaseline="middle"
                                                transform="rotate(-90)"
                                                style={{
                                                    fill: '#454545',
                                                    fontSize: 11,
                                                }}
                                            >
                                                {tick.value}
                                            </text>
                                        </g>
                                    );
                                },
                            }}
                            colors={{
                                type: "sequential",
                                colors: ["#2ecc71", "#e74c3c"],
                                minValue: min,
                                maxValue: max,
                            }}
                            emptyColor="#555555"
                            borderColor={{
                                from: "color",
                                modifiers: [["darker", 0.8]],
                            }}
                            inactiveOpacity={0.3}
                            labelTextColor={{
                                from: "color",
                                modifiers: [["darker", 1.8]],
                            }}
                            tooltip={({ cell }) => {
                                const day = cell.serieId;
                                const time = cell.data.x;
                                const value = cell.value ?? 0;
                                const formatted = formatMinutesToHours(value);
                                return (
                                    <div style={{
                                        background: 'white',
                                        padding: '8px 12px',
                                        border: '1px solid #ccc',
                                        borderRadius: '4px',
                                        boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
                                    }}>
                                        <div><strong>{day}</strong></div>
                                        <div>Time: {time}</div>
                                        <div>Duration: {formatted.replace('\n', ' ')}</div>
                                    </div>
                                );
                            }}
                            cellComponent={(props) => {
                                const { cell } = props;
                                const label = cell.formattedValue || String(cell.value);
                                const lines = label.split('\n');
                                const lineHeight = 12;
                                const totalHeight = lines.length * lineHeight;
                                const startY = cell.y + cell.height / 2 - totalHeight / 2 + lineHeight / 2;
                                
                                return (
                                    <g>
                                        <rect
                                            x={cell.x}
                                            y={cell.y}
                                            width={cell.width}
                                            height={cell.height}
                                            fill={cell.color}
                                            fillOpacity={cell.opacity}
                                            strokeWidth={1}
                                            stroke={cell.borderColor}
                                        />
                                        {lines.length > 0 && (
                                            <text
                                                x={cell.x + cell.width / 2}
                                                y={startY}
                                                textAnchor="middle"
                                                dominantBaseline="middle"
                                                fill={cell.labelTextColor}
                                                fontSize={11}
                                                fontWeight={600}
                                                pointerEvents="none"
                                            >
                                                {lines.map((line: string, index: number) => (
                                                    <tspan
                                                        key={index}
                                                        x={cell.x + cell.width / 2}
                                                        dy={index === 0 ? 0 : lineHeight}
                                                    >
                                                        {line}
                                                    </tspan>
                                                ))}
                                            </text>
                                        )}
                                    </g>
                                );
                            }}
                            legends={[
                                {
                                    anchor: "right",
                                    translateX: 30,
                                    translateY: 40,
                                    length: 400,
                                    thickness: 8,
                                    direction: "column",
                                    tickPosition: "after",
                                    tickSize: 3,
                                    tickSpacing: 4,
                                    tickOverlap: false,
                                    tickFormat: (value) => formatMinutesToHours(value),
                                    title: "Duration",
                                    titleAlign: "start",
                                    titleOffset: 4,
                                },
                            ]}
                        />
                    </Box>
                </Grid>
            </Grid>
        </Box>
    );
}

