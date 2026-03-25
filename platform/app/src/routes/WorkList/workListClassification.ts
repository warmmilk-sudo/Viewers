type ClassificationStudy = Record<string, unknown>;

type WorkListClassificationTreeNodeConfig = {
  id: string;
  label: string;
  description?: string;
  value?: string | string[];
  values?: string[];
  children?: WorkListClassificationTreeNodeConfig[];
};

type WorkListClassificationConfig = {
  title?: string;
  subtitle?: string;
  collapsedLabel?: string;
  valueField?: string;
  defaultValue?: string;
  hierarchyDelimiters?: string[];
  tree?: WorkListClassificationTreeNodeConfig[];
};

type WorkListClassificationNode = {
  id: string;
  label: string;
  description?: string;
  values: string[];
  children?: WorkListClassificationNode[];
};

const DEFAULT_HIERARCHY_DELIMITERS = ['/', '>', '|', '｜', '→', '::'];

function getStudyClassificationValues(
  study: ClassificationStudy,
  config?: WorkListClassificationConfig
): string[] {
  const values = normalizeValues(study[config?.valueField || 'categoryPath']);
  const fallbackValue = config?.defaultValue ? [config.defaultValue] : ['未分类'];

  if (!values.length) {
    return dedupe(fallbackValue);
  }
  return dedupe(values);
}

function buildConfiguredClassificationTree(
  tree: WorkListClassificationTreeNodeConfig[] = []
): WorkListClassificationNode[] {
  return tree
    .map(node => finalizeConfiguredNode(node))
    .sort(sortByLabel);
}

function buildLegacyClassificationTree(
  studies: ClassificationStudy[],
  config?: WorkListClassificationConfig
): WorkListClassificationNode[] {
  const hierarchyDelimiters =
    config?.hierarchyDelimiters?.length > 0
      ? config.hierarchyDelimiters
      : DEFAULT_HIERARCHY_DELIMITERS;
  const roots = new Map<string, LegacyTreeBuilderNode>();

  Array.from(new Set(studies.flatMap(study => getStudyClassificationValues(study, config)))).forEach(
    classificationValue => {
      const segments = splitClassificationPath(classificationValue, hierarchyDelimiters);
      const normalizedSegments = segments.length ? segments : [classificationValue];

      let currentMap = roots;
      const currentPath: string[] = [];

      normalizedSegments.forEach(segment => {
        currentPath.push(segment);
        const nodeKey = segment;
        const nodeId = currentPath.map(encodeURIComponent).join('::');
        let node = currentMap.get(nodeKey);

        if (!node) {
          node = {
            id: nodeId,
            label: segment,
            directValues: new Set<string>(),
            children: new Map<string, LegacyTreeBuilderNode>(),
          };
          currentMap.set(nodeKey, node);
        }

        currentMap = node.children;
      });

      const leafNode = getLegacyBuilderNodeByPath(roots, normalizedSegments);
      if (leafNode) {
        leafNode.directValues.add(classificationValue);
      }
    }
  );

  return Array.from(roots.values())
    .sort(sortByLabel)
    .map(node => finalizeLegacyTreeBuilderNode(node))
    .sort(sortByLabel);
}

function buildDisplayClassificationTree(
  studies: ClassificationStudy[],
  config?: WorkListClassificationConfig
): WorkListClassificationNode[] {
  const configuredTree = buildConfiguredClassificationTree(config?.tree || []);
  const dynamicTree = buildLegacyClassificationTree(studies, config);

  if (!configuredTree.length) {
    return dynamicTree;
  }

  if (!dynamicTree.length) {
    return configuredTree;
  }

  return mergeClassificationNodes(configuredTree, dynamicTree).sort(sortByLabel);
}

function finalizeConfiguredNode(
  node: WorkListClassificationTreeNodeConfig
): WorkListClassificationNode {
  const children = (node.children || []).map(child => finalizeConfiguredNode(child)).sort(sortByLabel);
  const childValues = children.flatMap(child => child.values);
  const ownValues = normalizeValues(node.value).concat(normalizeValues(node.values));
  const values = dedupe([...ownValues, ...childValues]);

  return {
    id: node.id,
    label: node.label,
    description: node.description,
    values,
    children: children.length ? children : undefined,
  };
}

function finalizeLegacyTreeBuilderNode(node: LegacyTreeBuilderNode): WorkListClassificationNode {
  const children = Array.from(node.children.values())
    .sort(sortByLabel)
    .map(child => finalizeLegacyTreeBuilderNode(child));
  const childValues = children.flatMap(child => child.values);
  const values = dedupe([...node.directValues, ...childValues]);

  return {
    id: node.id,
    label: node.label,
    values,
    children: children.length ? children : undefined,
  };
}

function mergeClassificationNodes(
  configuredNodes: WorkListClassificationNode[],
  dynamicNodes: WorkListClassificationNode[]
): WorkListClassificationNode[] {
  const merged = new Map<string, WorkListClassificationNode>();

  configuredNodes.forEach(node => {
    merged.set(node.label, cloneClassificationNode(node));
  });

  dynamicNodes.forEach(node => {
    const existing = merged.get(node.label);
    if (!existing) {
      merged.set(node.label, cloneClassificationNode(node));
      return;
    }

    merged.set(node.label, mergeClassificationNode(existing, node));
  });

  return Array.from(merged.values()).sort(sortByLabel);
}

function mergeClassificationNode(
  configuredNode: WorkListClassificationNode,
  dynamicNode: WorkListClassificationNode
): WorkListClassificationNode {
  return {
    ...configuredNode,
    values: dedupe([...configuredNode.values, ...dynamicNode.values]),
    children: mergeOptionalChildren(configuredNode.children, dynamicNode.children),
  };
}

function mergeOptionalChildren(
  configuredChildren?: WorkListClassificationNode[],
  dynamicChildren?: WorkListClassificationNode[]
) {
  const mergedChildren = mergeClassificationNodes(configuredChildren || [], dynamicChildren || []);
  return mergedChildren.length ? mergedChildren : undefined;
}

function cloneClassificationNode(node: WorkListClassificationNode): WorkListClassificationNode {
  return {
    ...node,
    values: [...node.values],
    children: node.children?.map(child => cloneClassificationNode(child)),
  };
}

function getLegacyBuilderNodeByPath(
  roots: Map<string, LegacyTreeBuilderNode>,
  segments: string[]
): LegacyTreeBuilderNode | undefined {
  let current: LegacyTreeBuilderNode | undefined;
  let currentMap = roots;

  for (const segment of segments) {
    current = currentMap.get(segment);
    if (!current) {
      return undefined;
    }

    currentMap = current.children;
  }

  return current;
}

function splitClassificationPath(value: string, hierarchyDelimiters: string[]) {
  const delimiters = hierarchyDelimiters
    .filter(Boolean)
    .slice()
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp);

  if (!delimiters.length) {
    return [value.trim()].filter(Boolean);
  }

  const pattern = new RegExp(`\\s*(?:${delimiters.join('|')})\\s*`);
  return value
    .split(pattern)
    .map(segment => segment.trim())
    .filter(Boolean);
}

function normalizeValues(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(item => `${item}`.trim()).filter(Boolean);
  }

  if (typeof value === 'string') {
    return value
      .split(',')
      .map(item => item.trim())
      .filter(Boolean);
  }

  return [];
}

function dedupe(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function sortByLabel(a: { label: string }, b: { label: string }) {
  const aIsUnclassified = a.label === '未分类';
  const bIsUnclassified = b.label === '未分类';

  if (aIsUnclassified && !bIsUnclassified) {
    return 1;
  }

  if (!aIsUnclassified && bIsUnclassified) {
    return -1;
  }

  return a.label.localeCompare(b.label, 'zh-CN', { numeric: true, sensitivity: 'base' });
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

type LegacyTreeBuilderNode = {
  id: string;
  label: string;
  directValues: Set<string>;
  children: Map<string, LegacyTreeBuilderNode>;
};

export type {
  ClassificationStudy,
  WorkListClassificationConfig,
  WorkListClassificationNode,
  WorkListClassificationTreeNodeConfig,
};
export {
  buildDisplayClassificationTree,
  buildConfiguredClassificationTree,
  buildLegacyClassificationTree,
  getStudyClassificationValues,
};
