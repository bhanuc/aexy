import { redirect } from "next/navigation";

/**
 * CRM Automations page - redirects to platform-wide automations with CRM filter.
 *
 * This redirect maintains backwards compatibility while consolidating
 * all automations under the /automations route.
 */
export default function CRMAutomationsPage() {
  redirect("/automations?module=crm");
}
