import { useEffect, useState, type MouseEvent, type ReactNode } from "react";

export function usePathname() {
  const [path, setPath] = useState(() => window.location.pathname || "/");
  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname || "/");
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  return path;
}

export function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useNavigate() {
  return navigate;
}

export function RouteLink({ to, className, activeProps, children, onClick }: { to: string; className?: string; activeProps?: { className?: string }; children: ReactNode; onClick?: (event: MouseEvent<HTMLAnchorElement>) => void }) {
  const path = usePathname();
  const active = path === to || (to !== "/" && path.startsWith(`${to}/`));
  return <a href={to} className={active && activeProps?.className ? `${className ?? ""} ${activeProps.className}` : className} onClick={(event) => { onClick?.(event); if (!event.defaultPrevented && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate(to); } }}>{children}</a>;
}
