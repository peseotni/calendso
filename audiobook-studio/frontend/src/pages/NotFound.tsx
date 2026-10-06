import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, EmptyState } from "../components/ui";

export default function NotFound() {
  return (
    <EmptyState
      icon={<Compass className="size-6" />}
      title="Page not found"
      description="The page you are looking for does not exist."
      action={
        <Link to="/">
          <Button variant="primary">Go to dashboard</Button>
        </Link>
      }
    />
  );
}
