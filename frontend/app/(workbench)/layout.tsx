import { WorkbenchShell } from '@/ui/shell/Workbench';

export default function WorkbenchLayout({ children }: { children: React.ReactNode }) {
  return <WorkbenchShell>{children}</WorkbenchShell>;
}
