"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import { ReadOnlyNotice } from "@/components/settings/service-desk/sections";
import { ScorecardSection } from "@/components/settings/service-desk/ScorecardSection";

export default function ServiceDeskScorecardSettingsPage() {
  const t = useTranslations("serviceDesk.reports.config");

  return (
    <SettingsGroupPage
      group="serviceDesk" title={t("title")} description={t("description")}>
      <div className="space-y-6">
        <ReadOnlyNotice />
        <ScorecardSection />
      </div>
    </SettingsGroupPage>
  );
}
