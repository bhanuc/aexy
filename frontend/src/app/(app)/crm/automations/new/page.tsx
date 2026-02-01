import { redirect } from "next/navigation";

/**
 * CRM New Automation page - redirects to platform-wide new automation with CRM preset.
 *
 * This redirect maintains backwards compatibility while consolidating
 * all automations under the /automations route.
 */
export default function NewCRMAutomationPage() {
  redirect("/automations/new?module=crm");
}
