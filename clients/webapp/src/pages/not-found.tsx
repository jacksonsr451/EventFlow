import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, EmptyState, PageLayout } from "@eventflow/ui";
import { useDocumentTitle } from "../lib/use-document-title";

export function NotFoundPage() {
  useDocumentTitle("Page not found");
  return (
    <PageLayout>
      <EmptyState
        icon={Compass}
        title="Page not found"
        description="The page you requested does not exist or may have moved. Use the navigation to continue working in EventFlow."
        action={
          <Button onClick={() => window.history.back()}>
            Go back
          </Button>
        }
      />
      <p className="mt-4 text-center text-sm text-muted-foreground">
        Or return to the{" "}
        <Link to="/" className="font-medium text-primary underline-offset-4 hover:underline">
          dashboard
        </Link>
        .
      </p>
    </PageLayout>
  );
}
