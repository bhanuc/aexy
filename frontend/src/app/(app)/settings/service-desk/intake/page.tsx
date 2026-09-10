"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import {
  IntakeSection,
  ReadOnlyNotice,
} from "@/components/settings/service-desk/sections";

export default function ServiceDeskIntakeSettingsPage() {
  const t = useTranslations("serviceDesk");

  return (
    <SettingsGroupPage
      group="serviceDesk"
      title={t("deskDepartment.title")}
      description={t("deskDepartment.description")}
    >
      <div className="space-y-6">
        <ReadOnlyNotice />
        <IntakeSection />
      </div>
    </SettingsGroupPage>
  );
}
