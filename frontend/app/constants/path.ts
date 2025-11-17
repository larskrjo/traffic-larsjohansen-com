let BASE_URL = 'https://api.traffic.larsjohansen.com';
if (import.meta.env.DEV) {
    BASE_URL = "http://api.traffic.larsjohansen.com:8000";
}

export const COMMUTE_HEATMAP_URL = BASE_URL + '/api/v1/commute/heatmap';