import { COMMUTE_HEATMAP_URL } from "~/constants/path";
import type {Route} from "./+types/index";
import HeatMap from "~/components/HeatMap";

type HeatmapApiResponse = {
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

export async function clientLoader() {
    try {
        const res = await fetch(COMMUTE_HEATMAP_URL);
        if (!res.ok) {
            throw new Error(`Failed to fetch: ${res.statusText}`);
        }
        const data: HeatmapApiResponse = await res.json();
        return { heatmapData: data };
    } catch (error) {
        console.error("Error fetching heatmap data:", error);
        return { heatmapData: null };
    }
}

export default function IndexPage({loaderData}: Route.ComponentProps) {
  return <HeatMap heatmapData={loaderData.heatmapData} />;
}
