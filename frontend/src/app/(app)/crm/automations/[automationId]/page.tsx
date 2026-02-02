import { redirect } from "next/navigation";

interface Props {
  params: Promise<{ automationId: string }>;
}

/**
 * CRM Edit Automation page - redirects to platform-wide automation editor.
 *
 * This redirect maintains backwards compatibility while consolidating
 * all automations under the /automations route.
 */
export default async function EditCRMAutomationPage({ params }: Props) {
  const { automationId } = await params;
  redirect(`/automations/${automationId}`);
}
