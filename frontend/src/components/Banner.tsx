export const DEMO_BANNER =
  "Demo / Fake Provider / DeepSeek 可配置 / 非自动批准";

export function Banner() {
  return (
    <div className="banner" role="status">
      {DEMO_BANNER}
    </div>
  );
}
