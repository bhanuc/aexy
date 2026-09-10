"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import {
  DigestSections,
  ReadOnlyNotice,
} from "@/components/settings/service-desk/sections";

export default function ServiceDeskDigestSettingsPage() {
  const t = useTranslations("serviceDesk");

  return (
    <SettingsGroupPage
      group="serviceDesk"
      title={t("digest.title")}
      description={t("digest.description")}
    >
      <div className="space-y-6">
        <ReadOnlyNotice />
        <DigestSections />
      </div>
    </SettingsGroupPage>
  );
}
