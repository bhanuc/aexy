"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import {
  ReadOnlyNotice,
  WorkingHoursSections,
} from "@/components/settings/service-desk/sections";

export default function ServiceDeskHoursSettingsPage() {
  const t = useTranslations("serviceDesk");

  return (
    <SettingsGroupPage
      group="serviceDesk"
      title={t("workingHours.title")}
      description={t("workingHours.description")}
    >
      <div className="space-y-6">
        <ReadOnlyNotice />
        <WorkingHoursSections />
      </div>
    </SettingsGroupPage>
  );
}
