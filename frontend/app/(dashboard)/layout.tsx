import { Sidebar } from '@/components/ui/Sidebar'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-[280px_1fr] min-h-screen">
      <Sidebar />
      <main className="overflow-auto bg-slateDeep-950">
        {children}
      </main>
    </div>
  )
}
