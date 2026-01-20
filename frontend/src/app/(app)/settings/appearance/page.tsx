"use client";

import Link from "next/link";
import { ArrowLeft, Palette, LayoutGrid, List, Check } from "lucide-react";
import { useSidebarLayout } from "@/hooks/useSidebarLayout";
import { SidebarLayoutType, SIDEBAR_LAYOUTS } from "@/config/sidebarLayouts";

const LAYOUT_OPTIONS: {
    id: SidebarLayoutType;
    name: string;
    description: string;
    icon: React.ReactNode;
    preview: string[];
}[] = [
    {
        id: "grouped",
        name: "Grouped",
        description: "Items organized by functional areas (Engineering, People, Business, Knowledge)",
        icon: <LayoutGrid className="h-5 w-5" />,
        preview: ["Dashboard", "Engineering", "  Tracking", "  Planning", "  Tickets", "People", "  Reviews", "  Hiring", "  Learning", "Business", "  CRM", "  Email", "Knowledge", "  Docs", "  Forms"],
    },
    {
        id: "flat",
        name: "Flat",
        description: "All features at the top level for quick access",
        icon: <List className="h-5 w-5" />,
        preview: ["Dashboard", "Tracking", "Planning", "Tickets", "Reviews", "Hiring", "CRM", "Learning", "Docs", "Forms"],
    },
];

export default function AppearanceSettingsPage() {
    const { layout, setLayout, isLoaded } = useSidebarLayout();

    const handleLayoutChange = (newLayout: SidebarLayoutType) => {
        setLayout(newLayout);
    };

    return (
        <div className="min-h-screen bg-slate-900">
            {/* Header */}
            <header className="border-b border-slate-700 bg-slate-800/50">
                <div className="max-w-3xl mx-auto px-4 py-4">
                    <div className="flex items-center gap-4">
                        <Link
                            href="/settings"
                            className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition"
                        >
                            <ArrowLeft className="h-5 w-5" />
                        </Link>
                        <div className="flex items-center gap-3">
                            <div className="p-2 bg-slate-700 rounded-lg">
                                <Palette className="h-5 w-5 text-indigo-400" />
                            </div>
                            <div>
                                <h1 className="text-xl font-semibold text-white">Appearance</h1>
                                <p className="text-slate-400 text-sm">
                                    Customize how the application looks
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            </header>

            <main className="max-w-3xl mx-auto px-4 py-8">
                {/* Sidebar Layout Section */}
                <div className="bg-slate-800 rounded-xl overflow-hidden">
                    <div className="p-4 border-b border-slate-700">
                        <h3 className="text-white font-medium">Sidebar Layout</h3>
                        <p className="text-slate-400 text-sm mt-1">
                            Choose how navigation items are organized in the sidebar
                        </p>
                    </div>

                    <div className="p-4 grid gap-4 md:grid-cols-2">
                        {LAYOUT_OPTIONS.map((option) => {
                            const isSelected = layout === option.id;

                            return (
                                <button
                                    key={option.id}
                                    onClick={() => handleLayoutChange(option.id)}
                                    className={`relative p-4 rounded-lg border-2 text-left transition-all ${
                                        isSelected
                                            ? "border-indigo-500 bg-indigo-500/10"
                                            : "border-slate-600 hover:border-slate-500 bg-slate-700/30"
                                    }`}
                                >
                                    {/* Selected indicator */}
                                    {isSelected && (
                                        <div className="absolute top-3 right-3 p-1 bg-indigo-500 rounded-full">
                                            <Check className="h-3 w-3 text-white" />
                                        </div>
                                    )}

                                    {/* Header */}
                                    <div className="flex items-center gap-3 mb-3">
                                        <div className={`p-2 rounded-lg ${isSelected ? "bg-indigo-500/20 text-indigo-400" : "bg-slate-600 text-slate-300"}`}>
                                            {option.icon}
                                        </div>
                                        <div>
                                            <h4 className="text-white font-medium">{option.name}</h4>
                                        </div>
                                    </div>

                                    {/* Description */}
                                    <p className="text-slate-400 text-sm mb-4">
                                        {option.description}
                                    </p>

                                    {/* Preview */}
                                    <div className="bg-slate-800 rounded-lg p-3 border border-slate-600">
                                        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 font-medium">
                                            Preview
                                        </p>
                                        <div className="space-y-1 max-h-40 overflow-y-auto">
                                            {option.preview.map((item, idx) => {
                                                const isSection = !item.startsWith("  ");
                                                const displayText = item.trim();

                                                if (isSection && option.id === "grouped" && idx > 0) {
                                                    return (
                                                        <p
                                                            key={idx}
                                                            className="text-[10px] uppercase tracking-wider text-slate-500 font-medium pt-2"
                                                        >
                                                            {displayText}
                                                        </p>
                                                    );
                                                }

                                                return (
                                                    <div
                                                        key={idx}
                                                        className={`text-xs py-0.5 ${
                                                            !isSection ? "pl-3 text-slate-400" : "text-slate-300"
                                                        }`}
                                                    >
                                                        {displayText}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                </button>
                            );
                        })}
                    </div>

                    <div className="px-4 pb-4">
                        <p className="text-xs text-slate-500">
                            Changes are saved automatically and will take effect immediately.
                        </p>
                    </div>
                </div>
            </main>
        </div>
    );
}
