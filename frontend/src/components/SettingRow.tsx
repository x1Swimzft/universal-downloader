import React from "react";

export interface SettingRowProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export function SettingRow({ title, subtitle, children }: SettingRowProps) {
  return (
    <div className="row">
      <div>
        {title}
        {subtitle && <small>{subtitle}</small>}
      </div>
      {children}
    </div>
  );
}
