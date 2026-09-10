"use client";

import { useTranslations } from "next-intl";

import { SettingsGroupPage } from "@/components/settings/SettingsGroupPage";
import {
  MailboxesSection,
  ReadOnlyNotice,
} from "@/components/settings/service-desk/sections";

export default function ServiceDeskMailboxesSettingsPage() {
  const t = useTranslations("serviceDesk");

  return (
    <SettingsGroupPage
      group="serviceDesk"
      title={t("settings.mailboxes")}
      description={t("settings.mailboxesHint")}
    >
      <div className="space-y-6">
        <ReadOnlyNotice />
        <MailboxesSection />
      </div>
    </SettingsGroupPage>
  );
}
