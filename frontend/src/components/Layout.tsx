import type { ReactNode } from "react";
import { ACTOR_ID, ACTOR_TYPE } from "../api";
import { Banner } from "./Banner";

const LINKS: Array<{ href: string; label: string }> = [
  { href: "#/overview", label: "总览" },
  { href: "#/project", label: "项目" },
  { href: "#/canon", label: "Canon" },
  { href: "#/scene", label: "场景" },
  { href: "#/validation", label: "校验" },
  { href: "#/review", label: "审校" },
  { href: "#/dag", label: "DAG" },
  { href: "#/release", label: "发布门" },
];

export function Layout({
  page,
  children,
}: {
  page: string;
  children: ReactNode;
}) {
  return (
    <>
      <Banner />
      <div className="layout">
        <nav>
          <h1>工作流 Demo</h1>
          {LINKS.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className={page === item.href.slice(2) ? "active" : undefined}
            >
              {item.label}
            </a>
          ))}
          <div className="actor">
            演员：{ACTOR_ID} / {ACTOR_TYPE}
          </div>
        </nav>
        <main>{children}</main>
      </div>
    </>
  );
}
