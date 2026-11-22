import { WorkbenchShell } from '@/ui/shell/Workbench';

export default function SetupLayout({ children }: { children: React.ReactNode }) {
  return <WorkbenchShell bare>{children}</WorkbenchShell>;
}
