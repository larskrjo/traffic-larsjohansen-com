import Unknown from "~/components/Unknown";
import type {Route} from "../../.react-router/types/app/+types/root";

export function meta({}: Route.MetaArgs) {
    return [
        { title: "Error!" },
        { name: "description", content: "Unknown error" },
    ];
}

export default function UnknownPage() {
  return <Unknown />;
}
