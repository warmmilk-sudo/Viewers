import React, { useEffect, useMemo, useState } from 'react';
import classnames from 'classnames';
import { Icons, ScrollArea } from '@ohif/ui-next';

import {
  buildDisplayClassificationTree,
  getStudyClassificationValues,
  type ClassificationStudy,
  type WorkListClassificationConfig,
  type WorkListClassificationNode,
} from './workListClassification';

type WorkListSidebarProps = {
  studies: ClassificationStudy[];
  activeCategoryValues: string[];
  onSelectCategoryValues: (values: string[]) => void;
  isCollapsed: boolean;
  onToggleCollapsed: () => void;
  sidebarConfig?: WorkListClassificationConfig;
};

function WorkListSidebar({
  studies,
  activeCategoryValues,
  onSelectCategoryValues,
  isCollapsed,
  onToggleCollapsed,
  sidebarConfig,
}: WorkListSidebarProps) {
  const treeItems = useMemo(() => {
    return buildDisplayClassificationTree(studies, sidebarConfig);
  }, [sidebarConfig, studies]);

  const activeValueSet = useMemo(
    () => new Set(activeCategoryValues.filter(Boolean)),
    [activeCategoryValues]
  );

  const initialExpandedIds = useMemo(
    () => treeItems.filter(item => item.children?.length).map(item => item.id),
    [treeItems]
  );
  const [expandedNodeIds, setExpandedNodeIds] = useState<string[]>(initialExpandedIds);

  useEffect(() => {
    setExpandedNodeIds(currentExpanded => {
      const existingIds = new Set(collectNodeIds(treeItems));
      const nextExpanded = currentExpanded.filter(id => existingIds.has(id));

      return nextExpanded.length ? nextExpanded : initialExpandedIds;
    });
  }, [initialExpandedIds, treeItems]);

  const studyCountsByNode = useMemo(() => {
    const counts = new Map<string, number>();

    const countNode = (node: WorkListClassificationNode): void => {
      const valueSet = new Set(node.values);
      const patientKeys = new Set<string>();

      studies.forEach(study => {
        const studyValues = getStudyClassificationValues(study, sidebarConfig);
        if (studyValues.some(value => valueSet.has(value))) {
          patientKeys.add(getStudyPatientKey(study));
        }
      });

      counts.set(node.id, patientKeys.size);
      node.children?.forEach(countNode);
    };

    treeItems.forEach(countNode);

    return counts;
  }, [sidebarConfig, studies, treeItems]);

  const handleNodeSelection = (node: WorkListClassificationNode) => {
    onSelectCategoryValues(node.values);
  };

  const toggleNode = (nodeId: string) => {
    setExpandedNodeIds(current =>
      current.includes(nodeId) ? current.filter(id => id !== nodeId) : [...current, nodeId]
    );
  };

  return (
    <aside
      className={classnames(
        'relative border-r border-white/10 bg-black transition-all duration-300 ease-out',
        isCollapsed ? 'w-[72px]' : 'w-[316px]'
      )}
    >
      <div className="relative flex h-full flex-col overflow-hidden">
        <div className="border-b border-white/10 px-3 py-3">
          <button
            type="button"
            onClick={onToggleCollapsed}
            className={classnames(
              'flex h-10 w-full items-center justify-center gap-2 rounded border border-white/10 bg-primary-dark text-white/75 transition hover:border-primary/40 hover:text-white',
              isCollapsed && 'px-0'
            )}
            aria-label={isCollapsed ? '展开侧边栏' : '收起侧边栏'}
          >
            <Icons.ArrowLeft
              className={classnames(
                'h-4 w-4 shrink-0 transition-transform',
                isCollapsed && 'rotate-180'
              )}
            />
            {!isCollapsed && <span className="text-sm font-medium">数据分类</span>}
          </button>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="px-2 py-3">
            <div className="space-y-2">
              {treeItems.map(node => (
                <SidebarNodeView
                  key={node.id}
                  node={node}
                  depth={0}
                  isCollapsed={isCollapsed}
                  expandedNodeIds={expandedNodeIds}
                  onToggleNode={toggleNode}
                  onSelectNode={handleNodeSelection}
                  countsByNode={studyCountsByNode}
                  isActive={hasActiveValue(node, activeValueSet)}
                  activeValueSet={activeValueSet}
                />
              ))}
            </div>
          </div>
        </ScrollArea>
      </div>
    </aside>
  );
}

function SidebarNodeView({
  node,
  depth,
  isCollapsed,
  expandedNodeIds,
  onToggleNode,
  onSelectNode,
  countsByNode,
  isActive,
  activeValueSet,
}: {
  node: WorkListClassificationNode;
  depth: number;
  isCollapsed: boolean;
  expandedNodeIds: string[];
  onToggleNode: (nodeId: string) => void;
  onSelectNode: (node: WorkListClassificationNode) => void;
  countsByNode: Map<string, number>;
  isActive: boolean;
  activeValueSet: Set<string>;
}) {
  const hasChildren = !!node.children?.length;
  const isExpanded = hasChildren
    ? expandedNodeIds.includes(node.id) || hasActiveValue(node, activeValueSet)
    : false;
  const count = countsByNode.get(node.id) || 0;
  const displayLabel = node.label;

  return (
    <div className="space-y-1">
      {!isCollapsed ? (
        <div
          className={classnames(
            'group flex items-stretch gap-2 rounded border px-3 py-2 transition duration-300',
            isActive
              ? 'border-primary-light bg-secondary-dark text-white'
              : 'border-secondary-light bg-primary-dark text-white/80 hover:bg-secondary-main',
            depth > 0 && 'ml-4'
          )}
          style={{
            paddingLeft: 12 + depth * 14,
          }}
          title={displayLabel}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={() => onToggleNode(node.id)}
              className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded border border-white/10 bg-black text-white/60 transition hover:border-primary/50 hover:text-white"
              aria-label={isExpanded ? '收起节点' : '展开节点'}
            >
              <Icons.ArrowLeft
                className={classnames('h-3 w-3 transition-transform', isExpanded && '-rotate-90')}
              />
            </button>
          ) : (
            <div className="mt-0.5 h-7 w-7 shrink-0" />
          )}

          <button
            type="button"
            onClick={() => onSelectNode(node)}
            className="min-w-0 flex-1 text-left"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{displayLabel}</div>
              </div>
              <span className="shrink-0 text-xs text-white/55">
                {count}
              </span>
            </div>
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => onSelectNode(node)}
          className={classnames(
            'flex w-full items-center justify-center rounded border px-2 py-2 transition duration-300',
            isActive
              ? 'border-primary-light bg-secondary-dark text-white'
              : 'border-secondary-light bg-primary-dark text-white/80 hover:bg-secondary-main'
          )}
          title={displayLabel}
        >
          <div className="flex h-8 w-8 items-center justify-center rounded bg-black text-[11px] font-semibold text-white/75">
            {abbreviateLabel(displayLabel)}
          </div>
        </button>
      )}

      {!isCollapsed && hasChildren && isExpanded && (
        <div className="space-y-1">
          {node.children!.map(child => (
            <SidebarNodeView
              key={child.id}
              node={child}
              depth={depth + 1}
              isCollapsed={isCollapsed}
              expandedNodeIds={expandedNodeIds}
              onToggleNode={onToggleNode}
              onSelectNode={onSelectNode}
              countsByNode={countsByNode}
              isActive={hasActiveValue(child, activeValueSet)}
              activeValueSet={activeValueSet}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function getStudyPatientKey(study: ClassificationStudy) {
  const mrn = `${study.mrn ?? ''}`.trim();
  if (mrn) {
    return `mrn:${mrn}`;
  }

  const studyInstanceUid = `${study.studyInstanceUid ?? ''}`.trim();
  if (studyInstanceUid) {
    return `study:${studyInstanceUid}`;
  }

  const patientName = `${study.patientName ?? ''}`.trim();
  if (patientName) {
    return `patient:${patientName}`;
  }

  return 'unknown';
}

function hasActiveValue(node: WorkListClassificationNode, activeValueSet: Set<string>) {
  return node.values.some(value => activeValueSet.has(value));
}

function collectNodeIds(nodes: WorkListClassificationNode[]): string[] {
  const ids: string[] = [];

  const walk = (node: WorkListClassificationNode) => {
    ids.push(node.id);
    node.children?.forEach(walk);
  };

  nodes.forEach(walk);

  return ids;
}

function abbreviateLabel(label: string) {
  if (!label) {
    return '组';
  }

  const trimmed = label.replace(/\s+/g, '');
  if (trimmed.length <= 2) {
    return trimmed;
  }

  return trimmed.slice(0, 2);
}

export type { WorkListClassificationConfig as WorkListSidebarConfig };
export default WorkListSidebar;
