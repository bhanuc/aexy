"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import { ReadOnlyNotice } from "@/components/settings/service-desk/sections";
import { StakeholdersSection } from "@/components/settings/service-desk/StakeholdersSection";

export default function ServiceDeskStakeholdersSettingsPage() {
  const t = useTranslations("serviceDesk");

  return (
    <SettingsGroupPage
      group="serviceDesk"
      title={t("stakeholders.title")}
      description={t("stakeholders.description")}
    >
      <div className="space-y-6">
        <ReadOnlyNotice />
        <StakeholdersSection />
      </div>
    </SettingsGroupPage>
  );
}
