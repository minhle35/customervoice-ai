'use client'

import { useState } from 'react'
import { TopNav } from '@/components/ui/TopNav'
import { DataPipelineStarter } from '@/components/data-sources/data-pipeline-starter'
import { DataPipeline } from '@/components/data-sources/data-pipeline'

export default function DataSourcesPage() {
  const [taskId, setTaskId] = useState<string | null>(null)

  return (
    <>
      <TopNav
        title="Data Sources"
        subtitle="Configure and run review ingestion pipelines"
      />

      <div className="p-6 max-w-2xl space-y-6">
        {taskId ? (
          <DataPipeline taskId={taskId} onReset={() => setTaskId(null)} />
        ) : (
          <DataPipelineStarter onStarted={(id) => setTaskId(id)} />
        )}
      </div>
    </>
  )
}
