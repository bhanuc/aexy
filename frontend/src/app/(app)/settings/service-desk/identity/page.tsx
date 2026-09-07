"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import {
  IdentitySections,
  ReadOnlyNotice,
} from "@/components/settings/service-desk/sections";

export default function ServiceDeskIdentitySettingsPage() {
  const t = useTranslations("serviceDesk");

  return (
    <SettingsGroupPage
      group="serviceDesk"
      title={t("deskIdentity.title")}
      description={t("deskIdentity.description")}
    >
      <div className="space-y-6">
        <ReadOnlyNotice />
        <IdentitySections />
      </div>
    </SettingsGroupPage>
  );
}
