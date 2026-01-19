"use client";

import Link from "next/link";
import { ArrowRight, Heart, Lightbulb, Rocket, Users, Code2, Target } from "lucide-react";
import { LandingHeader, LandingFooter } from "@/components/landing/LandingHeader";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export default function StoryPage() {
  const googleLoginUrl = `${API_BASE_URL}/auth/google/login`;

  return (
    <div className="min-h-screen bg-[#0a0a0f] overflow-hidden">
      {/* Animated Background */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-primary-500/10 rounded-full blur-[120px] animate-pulse" />
        <div className="absolute top-1/3 right-1/4 w-[500px] h-[500px] bg-purple-500/10 rounded-full blur-[120px] animate-pulse" />
        <div className="absolute bottom-1/4 left-1/3 w-[400px] h-[400px] bg-emerald-500/8 rounded-full blur-[100px] animate-pulse" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:64px_64px]" />
      </div>

      <LandingHeader />

      {/* Hero */}
      <section className="pt-32 pb-16 px-6 relative">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-12">
            <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-primary-500/20 to-purple-500/20 border border-primary-500/30 rounded-full text-primary-400 text-sm mb-6">
              <Heart className="h-4 w-4" />
              Our Story
            </div>
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-white mb-6 tracking-tight leading-tight">
              Built by engineers,{" "}
              <span className="bg-gradient-to-r from-primary-400 to-purple-400 bg-clip-text text-transparent">
                for engineers.
              </span>
            </h1>
            <p className="text-xl text-white/60 max-w-2xl mx-auto">
              The story of how frustration with fragmented tools led to building something better.
            </p>
          </div>
        </div>
      </section>

      {/* Main Content */}
      <section className="py-12 px-6 relative">
        <div className="max-w-3xl mx-auto">
          {/* The Beginning */}
          <div className="mb-16">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-gradient-to-br from-primary-500/20 to-purple-500/20 rounded-xl flex items-center justify-center">
                <Lightbulb className="h-5 w-5 text-primary-400" />
              </div>
              <h2 className="text-2xl md:text-3xl font-bold text-white">The Beginning</h2>
            </div>
            <p className="text-white/70 leading-relaxed text-lg mb-6">
              It started with a simple observation: engineering teams were drowning in tools. Code lived in GitHub,
              tasks in Jira, docs in Notion, reviews in spreadsheets, and hiring in yet another system. Every tool
              told a different story, and no one had the complete picture.
            </p>
            <p className="text-white/70 leading-relaxed text-lg">
              We watched engineering managers spend hours reconciling data across systems. We saw talented developers
              frustrated by endless context switching. We witnessed leadership making decisions based on incomplete
              information. Something had to change.
            </p>
          </div>

          {/* The Problem */}
          <div className="relative mb-16 pl-6 border-l-4 border-primary-500">
            <p className="text-xl md:text-2xl text-white/90 italic leading-relaxed">
              &ldquo;We weren&apos;t just building another tool. We were building the connective tissue that
              engineering organizations desperately needed.&rdquo;
            </p>
          </div>

          {/* The Journey */}
          <div className="mb-16">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-gradient-to-br from-emerald-500/20 to-teal-500/20 rounded-xl flex items-center justify-center">
                <Rocket className="h-5 w-5 text-emerald-400" />
              </div>
              <h2 className="text-2xl md:text-3xl font-bold text-white">The Journey</h2>
            </div>
            <p className="text-white/70 leading-relaxed text-lg mb-6">
              We started Aexy with a radical idea: what if there was one platform that understood the entire
              engineering organization? Not just the code, but the people, the processes, the growth, and the
              customers they serve.
            </p>
            <p className="text-white/70 leading-relaxed text-lg mb-6">
              We built it open-source because we believe transparency breeds trust. Engineering organizations
              shouldn&apos;t have to rely on black boxes to manage their most critical operations.
            </p>
            <p className="text-white/70 leading-relaxed text-lg">
              Every feature we&apos;ve built comes from real pain points we&apos;ve experienced ourselves. Sprint planning
              that actually reflects capacity. Performance reviews that feel fair. Hiring assessments based on
              real skills. Documentation that stays connected to the work.
            </p>
          </div>

          {/* What We Believe */}
          <div className="mb-16">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-gradient-to-br from-purple-500/20 to-pink-500/20 rounded-xl flex items-center justify-center">
                <Target className="h-5 w-5 text-purple-400" />
              </div>
              <h2 className="text-2xl md:text-3xl font-bold text-white">What We Believe</h2>
            </div>
            <div className="space-y-4">
              {[
                { icon: Code2, text: "Code is the most honest data an engineering organization produces" },
                { icon: Users, text: "Great tools should empower teams, not surveil them" },
                { icon: Heart, text: "Transparency and trust are the foundation of high-performing teams" },
                { icon: Rocket, text: "World-class tools should be accessible to everyone, not just giants" },
              ].map((item, idx) => (
                <div key={idx} className="flex items-start gap-4 p-4 bg-white/5 rounded-xl border border-white/10">
                  <item.icon className="h-5 w-5 text-primary-400 flex-shrink-0 mt-0.5" />
                  <span className="text-white/80">{item.text}</span>
                </div>
              ))}
            </div>
          </div>

          {/* The Team */}
          <div className="mb-16">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500/20 to-cyan-500/20 rounded-xl flex items-center justify-center">
                <Users className="h-5 w-5 text-blue-400" />
              </div>
              <h2 className="text-2xl md:text-3xl font-bold text-white">The Team</h2>
            </div>
            <p className="text-white/70 leading-relaxed text-lg mb-6">
              We&apos;re a small team of engineers, designers, and dreamers who believe software can be a force for
              positive change. We&apos;ve worked at companies of all sizes and seen firsthand how the right tools
              can transform how teams operate.
            </p>
            <p className="text-white/70 leading-relaxed text-lg">
              We&apos;re building Aexy openly, transparently, and with the community. Because the best products
              are built together.
            </p>
          </div>
        </div>
      </section>

      {/* Quote Section */}
      <section className="py-24 px-6 relative">
        <div className="max-w-4xl mx-auto text-center">
          <div className="relative">
            <div className="absolute inset-0 bg-gradient-to-r from-primary-500/10 via-purple-500/10 to-emerald-500/10 rounded-3xl blur-xl" />
            <div className="relative bg-white/5 backdrop-blur-sm rounded-3xl p-12 border border-white/10">
              <p className="text-2xl md:text-3xl text-white font-medium leading-relaxed mb-6">
                &ldquo;The future of engineering organizations is integrated, transparent, and built on trust.
                We&apos;re here to make that future a reality.&rdquo;
              </p>
              <p className="text-white/50">The Aexy Team</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-16 px-6">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-6">
            Join us on this journey
          </h2>
          <p className="text-xl text-white/50 mb-10 max-w-2xl mx-auto">
            Whether you&apos;re building the next big thing or optimizing your team&apos;s operations,
            we&apos;d love to have you along for the ride.
          </p>

          <div className="flex flex-col sm:flex-row justify-center gap-4">
            <a
              href={googleLoginUrl}
              className="group inline-flex items-center justify-center gap-3 bg-white text-black px-8 py-4 rounded-full text-lg font-semibold transition-all hover:scale-105"
            >
              Get Started Free
              <ArrowRight className="h-5 w-5 group-hover:translate-x-1 transition-transform" />
            </a>
            <Link
              href="/manifesto"
              className="group bg-white/5 hover:bg-white/10 text-white px-8 py-4 rounded-full text-lg font-semibold transition-all border border-white/10 hover:border-white/20 flex items-center justify-center gap-3"
            >
              Read the Manifesto
            </Link>
          </div>
        </div>
      </section>

      <LandingFooter />
    </div>
  );
}
