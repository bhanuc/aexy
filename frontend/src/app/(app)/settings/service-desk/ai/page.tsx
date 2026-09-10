"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import {
  AiSections,
  ReadOnlyNotice,
} from "@/components/settings/service-desk/sections";

export default function ServiceDeskAiSettingsPage() {
  const t = useTranslations("serviceDesk");

  return (
    <SettingsGroupPage
      group="serviceDesk"
      title={t("ai.title")}
      description={t("ai.description")}
    >
      <div className="space-y-6">
        <ReadOnlyNotice />
        <AiSections />
      </div>
    </SettingsGroupPage>
  );
}
