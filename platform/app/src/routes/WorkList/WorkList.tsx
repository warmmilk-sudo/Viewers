import React, { useState, useEffect, useMemo } from 'react';
import classnames from 'classnames';
import PropTypes from 'prop-types';
import { Link, useNavigate } from 'react-router-dom';
import moment from 'moment';
import qs from 'query-string';
import isEqual from 'lodash.isequal';
import { useTranslation } from 'react-i18next';
//
import filtersMeta from './filtersMeta.js';
import { useAppConfig } from '@state';
import { useDebounce, useSearchParams } from '../../hooks';
import { utils, Types as coreTypes } from '@ohif/core';

import {
  StudyListExpandedRow,
  EmptyStudies,
  StudyListTable,
  StudyListTableRow,
  StudyListPagination,
  Button,
  ButtonEnums,
  InputFilterText,
} from '@ohif/ui';

import {
  Header,
  Icons,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  Clipboard,
  useModal,
  useSessionStorage,
  Onboarding,
  InvestigationalUseDialog,
  DatePickerWithRange,
} from '@ohif/ui-next';

import { Types } from '@ohif/ui';

import { preserveQueryParameters, preserveQueryStrings } from '../../utils/preserveQueryParameters';
import WorkListSidebar from './WorkListSidebar';
import { getStudyClassificationValues } from './workListClassification';

const PatientInfoVisibility = Types.PatientInfoVisibility;

const { sortBySeriesDate } = utils;

const seriesInStudiesMap = new Map();
const STUDY_LIST_GRID_WIDTH_CLASSES = {
  1: 'w-1/24',
  2: 'w-2/24',
  3: 'w-3/24',
  4: 'w-4/24',
  5: 'w-5/24',
  6: 'w-6/24',
  7: 'w-7/24',
  8: 'w-8/24',
  9: 'w-9/24',
  10: 'w-10/24',
  11: 'w-11/24',
  12: 'w-12/24',
  13: 'w-13/24',
  14: 'w-14/24',
  15: 'w-15/24',
  16: 'w-16/24',
  17: 'w-17/24',
  18: 'w-18/24',
  19: 'w-19/24',
  20: 'w-20/24',
  21: 'w-21/24',
  22: 'w-22/24',
  23: 'w-23/24',
  24: 'w-24/24',
};

const OUTER_STUDY_COLUMNS = [
  { key: 'patientName', label: '患者姓名', gridCol: 4 },
  { key: 'mrn', label: '病例号', gridCol: 3 },
  { key: 'studyDate', label: '检查日期', gridCol: 8 },
  { key: 'sex', label: '性别', gridCol: 2 },
  { key: 'age', label: '年龄', gridCol: 2 },
  { key: 'instances', label: '图像数', gridCol: 5 },
];

const INNER_STUDY_COLUMNS = [
  { key: 'studyId', label: '检查ID', gridCol: 6 },
  { key: 'studyDate', label: '检查日期', gridCol: 6 },
  { key: 'description', label: '描述', gridCol: 5 },
  { key: 'modality', label: '成像设备', gridCol: 4 },
  { key: 'instances', label: '图像数', gridCol: 3 },
];

const SORTABLE_COLUMN_KEYS = new Set(['patientName', 'mrn', 'studyDate', 'sex', 'age']);

function getStudyListGridWidthClass(gridCol) {
  return STUDY_LIST_GRID_WIDTH_CLASSES[gridCol] || '';
}

function renderStudyListHeader(columns, { canSort = false, sortBy = '', sortDirection = 'none', onSort } = {}) {
  return (
    <div className="flex w-full items-stretch border-b border-white/10 bg-primary-dark/80 text-xs font-medium text-white/65">
      {columns.map((column, index) => (
        <div
          key={column.key}
          className={classnames(
            'flex min-w-0 items-center px-4 py-2',
            getStudyListGridWidthClass(column.gridCol),
            column.alignRight && 'justify-end text-right',
            canSort && SORTABLE_COLUMN_KEYS.has(column.key) && 'cursor-pointer select-none'
          )}
          onClick={
            canSort && SORTABLE_COLUMN_KEYS.has(column.key) && onSort
              ? () => onSort(column.key)
              : undefined
          }
        >
          {index === 0 && <div className="mr-4 h-4 w-4 shrink-0" />}
          <span className="truncate">{column.label}</span>
          {canSort && SORTABLE_COLUMN_KEYS.has(column.key) && (
            <span className="ml-2 inline-flex shrink-0 text-primary-main">
              {sortBy === column.key ? (
                sortDirection === 'ascending' ? (
                  <Icons.SortingAscending className="w-2" />
                ) : (
                  <Icons.SortingDescending className="w-2" />
                )
              ) : (
                <Icons.Sorting className="w-2" />
              )}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function renderStudyListFilterRow({
  filterValues,
  onChange,
  clearFilters,
  isFiltering,
  clearFiltersLabel,
}) {
  const handleTextChange = name => value => {
    onChange({
      ...filterValues,
      [name]: value,
    });
  };

  const handleDateRangeChange = ({ startDate, endDate }) => {
    onChange({
      ...filterValues,
      studyDate: {
        startDate: startDate || null,
        endDate: endDate || null,
      },
    });
  };

  return (
    <div className="flex w-full items-stretch border-b border-white/10 bg-primary-dark/80 text-white">
      <div className={classnames('min-w-0 px-4 py-2', getStudyListGridWidthClass(4))}>
        <InputFilterText
          className="w-full"
          placeholder=""
          value={filterValues.patientName || ''}
          onChange={handleTextChange('patientName')}
        />
      </div>
      <div className={classnames('min-w-0 px-4 py-2', getStudyListGridWidthClass(3))}>
        <InputFilterText
          className="w-full"
          placeholder=""
          value={filterValues.mrn || ''}
          onChange={handleTextChange('mrn')}
        />
      </div>
      <div className={classnames('min-w-0 px-4 py-2', getStudyListGridWidthClass(8))}>
        <DatePickerWithRange
          className="w-full"
          id="studyDate"
          startDate={filterValues.studyDate?.startDate || ''}
          endDate={filterValues.studyDate?.endDate || ''}
          onChange={handleDateRangeChange}
        />
      </div>
      <div className={classnames('min-w-0 px-4 py-2', getStudyListGridWidthClass(2))}>
        <InputFilterText
          className="w-full"
          placeholder=""
          value={filterValues.sex || ''}
          onChange={handleTextChange('sex')}
        />
      </div>
      <div className={classnames('min-w-0 px-4 py-2', getStudyListGridWidthClass(2))}>
        <InputFilterText
          className="w-full"
          placeholder=""
          value={filterValues.age || ''}
          onChange={handleTextChange('age')}
        />
      </div>
      <div className={classnames('flex min-w-0 items-center px-4 py-2', getStudyListGridWidthClass(5))}>
        {isFiltering ? (
          <Button
            type={ButtonEnums.type.secondary}
            size={ButtonEnums.size.small}
            startIcon={<Icons.Cancel />}
            onClick={clearFilters}
            className="whitespace-nowrap"
          >
            {clearFiltersLabel}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function normalizeCategoryValues(value) {
  return Array.isArray(value) ? value.filter(Boolean) : value ? [value].filter(Boolean) : [];
}

function getStudyInstanceUid(study) {
  return `${study.studyInstanceUid || ''}`.trim();
}

function getStudyMrn(study) {
  return `${study.mrn || ''}`.trim();
}

function getStudyDateTimestamp(study) {
  const parsed = moment(study?.date, ['YYYYMMDD', 'YYYY.MM.DD'], true);
  return parsed.isValid() ? parsed.valueOf() : undefined;
}

function getStudyDateLabel(study, t) {
  const studyDate =
    study?.date &&
    moment(study.date, ['YYYYMMDD', 'YYYY.MM.DD'], true).isValid() &&
    moment(study.date, ['YYYYMMDD', 'YYYY.MM.DD']).format(t('Common:localDateFormat', 'MMM-DD-YYYY'));
  const studyTime =
    study?.time &&
    moment(study.time, ['HH', 'HHmm', 'HHmmss', 'HHmmss.SSS']).isValid() &&
    moment(study.time, ['HH', 'HHmm', 'HHmmss', 'HHmmss.SSS']).format(
      t('Common:localTimeFormat', 'hh:mm A')
    );

  return [studyDate, studyTime].filter(Boolean).join(' ');
}

function getStudyDateRangeLabel(studies, t) {
  const timestamps = studies
    .map(study => ({
      timestamp: getStudyDateTimestamp(study),
      label: getStudyDateLabel(study, t),
    }))
    .filter(item => item.timestamp && item.label)
    .sort((a, b) => a.timestamp - b.timestamp);

  if (!timestamps.length) {
    return '';
  }

  if (timestamps.length === 1) {
    return timestamps[0].label;
  }

  return `${timestamps[0].label} - ${timestamps[timestamps.length - 1].label}`;
}

function getStudyInstancesTotal(studies) {
  return studies.reduce((total, study) => total + Number(study.instances || 0), 0);
}

function makeCopyTooltipCell(textValue) {
  if (!textValue) {
    return '';
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-pointer truncate">{textValue}</span>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        <div className="flex items-center justify-between gap-2">
          {textValue}
          <Clipboard>{textValue}</Clipboard>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

function groupStudiesByMrn(studies) {
  const groups = [];
  const groupMap = new Map();

  studies.forEach(study => {
    const mrn = getStudyMrn(study);
    const groupKey = mrn ? `mrn:${mrn}` : `study:${getStudyInstanceUid(study)}`;
    let group = groupMap.get(groupKey);

    if (!group) {
      group = {
        key: groupKey,
        mrn,
        studies: [],
      };
      groupMap.set(groupKey, group);
      groups.push(group);
    }

    group.studies.push(study);
  });

  return groups;
}

function getStudyGroupStudyKey(groupKey, study) {
  return `${groupKey}::${getStudyInstanceUid(study)}`;
}

/**
 * TODO:
 * - debounce `setFilterValues` (150ms?)
 */
function WorkList({
  data: studies,
  dataTotal: studiesTotal,
  isLoadingData,
  dataSource,
  hotkeysManager,
  dataPath,
  servicesManager,
}: withAppTypes) {
  const { show } = useModal();
  const { t } = useTranslation();
  // ~ Modes
  const [appConfig] = useAppConfig();
  // ~ Filters
  const searchParams = useSearchParams();
  const navigate = useNavigate();
  const STUDIES_LIMIT = 101;
  const queryFilterValues = _getQueryFilterValues(searchParams);
  const [sessionQueryFilterValues, updateSessionQueryFilterValues] = useSessionStorage({
    key: 'queryFilterValues',
    defaultValue: queryFilterValues,
    // ToDo: useSessionStorage currently uses an unload listener to clear the filters from session storage
    // so on systems that do not support unload events a user will NOT be able to alter any existing filter
    // in the URL, load the page and have it apply.
    clearOnUnload: true,
  });
  const { accession: _ignoredAccession, ...sanitizedSessionQueryFilterValues } =
    sessionQueryFilterValues || {};
  const { description: _ignoredDescription, modalities: _ignoredModalities, ...cleanSessionValues } =
    sanitizedSessionQueryFilterValues || {};
  const migratedSessionQueryFilterValues = {
    ...cleanSessionValues,
    categoryPath: normalizeCategoryValues(sanitizedSessionQueryFilterValues.categoryPath),
  };
  const [filterValues, _setFilterValues] = useState({
    ...defaultFilterValues,
    ...migratedSessionQueryFilterValues,
  });
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(true);

  const debouncedFilterValues = useDebounce(filterValues, 200);
  const { resultsPerPage, pageNumber, sortBy, sortDirection } = filterValues;
  const sidebarConfig = appConfig.workListClassification ?? appConfig.workListSidebar;

  /*
   * The default sort value keep the filters synchronized with runtime conditional sorting
   * Only applied if no other sorting is specified and there are less than 101 studies
   */

  const studiesForDisplay = useMemo(() => {
    const selectedCategoryValues = normalizeCategoryValues(filterValues.categoryPath);

    if (!selectedCategoryValues.length) {
      return studies;
    }

    const selectedValueSet = new Set(selectedCategoryValues);

    return studies.filter(study =>
      getStudyClassificationValues(study, sidebarConfig).some(value => selectedValueSet.has(value))
    );
  }, [sidebarConfig, studies, filterValues.categoryPath]);

  const canSort = studiesForDisplay.length < STUDIES_LIMIT;
  const shouldUseDefaultSort = sortBy === '' || !sortBy;
  const sortModifier = sortDirection === 'descending' ? 1 : -1;
  const { customizationService } = servicesManager.services;

  const sortedStudies = useMemo(() => {
    if (!canSort) {
      return studiesForDisplay;
    }

    return [...studiesForDisplay].sort((s1, s2) => {
      if (shouldUseDefaultSort) {
        const ascendingSortModifier = -1;
        return _sortStringDates(s1, s2, ascendingSortModifier);
      }

      const s1Prop = s1[sortBy];
      const s2Prop = s2[sortBy];

      if (typeof s1Prop === 'string' && typeof s2Prop === 'string') {
        return s1Prop.localeCompare(s2Prop) * sortModifier;
      } else if (typeof s1Prop === 'number' && typeof s2Prop === 'number') {
        return (s1Prop > s2Prop ? 1 : -1) * sortModifier;
      } else if (!s1Prop && s2Prop) {
        return -1 * sortModifier;
      } else if (!s2Prop && s1Prop) {
        return 1 * sortModifier;
      } else if (sortBy === 'studyDate') {
        return _sortStringDates(s1, s2, sortModifier);
      }

      return 0;
    });
  }, [canSort, studiesForDisplay, shouldUseDefaultSort, sortBy, sortModifier]);

  const groupedStudies = useMemo(() => groupStudiesByMrn(sortedStudies), [sortedStudies]);
  const studiesByRowKey = useMemo(() => {
    const map = new Map();

    groupedStudies.forEach(group => {
      group.studies.forEach(study => {
        map.set(getStudyGroupStudyKey(group.key, study), { group, study });
      });
    });

    return map;
  }, [groupedStudies]);

  // ~ Rows & Studies
  const [expandedRows, setExpandedRows] = useState([]);
  const [expandedStudyRows, setExpandedStudyRows] = useState([]);
  const [studiesWithSeriesData, setStudiesWithSeriesData] = useState([]);
  const numOfStudies = groupedStudies.length;
  const querying = useMemo(() => {
    return isLoadingData || expandedRows.length > 0 || expandedStudyRows.length > 0;
  }, [isLoadingData, expandedRows, expandedStudyRows]);

  const setFilterValues = val => {
    const nextValues = { ...val };
    if (filterValues.pageNumber === nextValues.pageNumber) {
      nextValues.pageNumber = 1;
    }
    _setFilterValues(nextValues);
    updateSessionQueryFilterValues(nextValues);
    setExpandedRows([]);
    setExpandedStudyRows([]);
  };

  const handleSidebarSelection = (categoryValues: string[]) => {
    setFilterValues({
      ...filterValues,
      categoryPath: categoryValues,
      pageNumber: 1,
    });
  };

  const onPageNumberChange = newPageNumber => {
    const totalPages = Math.max(1, Math.ceil(numOfStudies / resultsPerPage));
    if (newPageNumber < 1 || newPageNumber > totalPages) {
      return;
    }

    setExpandedRows([]);
    setExpandedStudyRows([]);
    setFilterValues({ ...filterValues, pageNumber: newPageNumber });
  };

  const onResultsPerPageChange = newResultsPerPage => {
    setExpandedRows([]);
    setExpandedStudyRows([]);
    setFilterValues({
      ...filterValues,
      pageNumber: 1,
      resultsPerPage: Number(newResultsPerPage),
    });
  };

  // Set body style
  useEffect(() => {
    document.body.classList.add('bg-black');
    return () => {
      document.body.classList.remove('bg-black');
    };
  }, []);

  // Sync URL query parameters with filters
  useEffect(() => {
    if (!debouncedFilterValues) {
      return;
    }

    const queryString = {};
    Object.keys(defaultFilterValues).forEach(key => {
      const defaultValue = defaultFilterValues[key];
      const currValue = debouncedFilterValues[key];

      // TODO: nesting/recursion?
      if (key === 'studyDate') {
        if (currValue.startDate && defaultValue.startDate !== currValue.startDate) {
          queryString.startDate = currValue.startDate;
        }
        if (currValue.endDate && defaultValue.endDate !== currValue.endDate) {
          queryString.endDate = currValue.endDate;
        }
      } else if (key === 'modalities' || key === 'categoryPath') {
        if (Array.isArray(currValue) && currValue.length) {
          queryString[key] = currValue.join(',');
        }
      } else if (currValue !== defaultValue) {
        queryString[key] = currValue;
      }
    });

    preserveQueryStrings(queryString);

    const search = qs.stringify(queryString, {
      skipNull: true,
      skipEmptyString: true,
    });
    navigate({
      pathname: '/',
      search: search ? `?${search}` : undefined,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedFilterValues]);

  // Query for series information
  useEffect(() => {
    const fetchSeries = async studyInstanceUid => {
      try {
        const series = await dataSource.query.series.search(studyInstanceUid);
        seriesInStudiesMap.set(studyInstanceUid, sortBySeriesDate(series));
        setStudiesWithSeriesData(current =>
          current.includes(studyInstanceUid) ? current : [...current, studyInstanceUid]
        );
      } catch (ex) {
        // TODO: UI Notification Service
        console.warn(ex);
      }
    };

    for (let z = 0; z < expandedStudyRows.length; z++) {
      const rowInfo = studiesByRowKey.get(expandedStudyRows[z]);
      const study = rowInfo?.study;
      const studyInstanceUid = getStudyInstanceUid(study);

      if (!studyInstanceUid || studiesWithSeriesData.includes(studyInstanceUid)) {
        continue;
      }

      fetchSeries(studyInstanceUid);
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataSource, expandedStudyRows, studiesByRowKey, studiesWithSeriesData]);

  const isFiltering = (filterValues, defaultFilterValues) => {
    return !isEqual(filterValues, defaultFilterValues);
  };

  const offset = Math.max(0, (pageNumber - 1) * resultsPerPage);
  const offsetAndTake = offset + resultsPerPage;
  const tableDataSource = groupedStudies.slice(offset, offsetAndTake).map((group, key) => {
    const rowKey = offset + key + 1;
    const isExpanded = expandedRows.some(k => k === rowKey);
    const representativeStudy = group.studies[0] || {};
    const studyCount = group.studies.length;
    const patientName = representativeStudy.patientName || '';
    const mrn = group.mrn || getStudyMrn(representativeStudy);
    const studyDateLabel = studyCount > 1 ? getStudyDateRangeLabel(group.studies, t) : getStudyDateLabel(representativeStudy, t);
    const sex = representativeStudy.sex || '';
    const age = representativeStudy.age || '';
    const instances = getStudyInstancesTotal(group.studies);
    const summaryTitle =
      studyCount > 1
        ? `${studyCount} 项检查`
        : `${patientName || ''} ${mrn || ''}`.trim();

    const renderStudyExpandedContent = study => {
      const studyInstanceUid = getStudyInstanceUid(study);
      const studyModalities = `${study.modalities || ''}`;
      const modalitiesToCheck = studyModalities.replaceAll('/', '\\');
      const studyDate = getStudyDateLabel(study, t);

      return (
        <div
          key={studyInstanceUid}
          className="rounded border border-white/10 bg-primary-dark/20"
        >
          <div className="flex flex-wrap items-center gap-3 border-b border-white/10 px-4 py-3 text-sm text-white/75">
            <span className="font-medium text-white">{study.patientName || '(empty)'}</span>
            <span className="text-white/50">{study.mrn || ''}</span>
            <span className="text-white/50">{studyDate || ''}</span>
            <span className="text-white/50">{study.description || '(empty)'}</span>
            <span className="text-white/50">{studyModalities || ''}</span>
            <span className="text-white/50">{study.instances || 0}</span>
          </div>
          <StudyListExpandedRow
            seriesTableColumns={{
              description: t('StudyList:Description'),
              seriesNumber: t('StudyList:Series'),
              modality: t('StudyList:Modality'),
              instances: t('StudyList:Instances'),
            }}
            seriesTableDataSource={
              seriesInStudiesMap.has(studyInstanceUid)
                ? seriesInStudiesMap.get(studyInstanceUid).map(s => {
                    return {
                      description: s.description || '(empty)',
                      seriesNumber: s.seriesNumber ?? '',
                      modality: s.modality || '',
                      instances: s.numSeriesInstances || '',
                    };
                  })
                : []
            }
          >
            <div className="flex flex-row gap-2">
              {(appConfig.groupEnabledModesFirst
                ? appConfig.loadedModes.sort((a, b) => {
                    const isValidA = a.isValidMode({
                      modalities: modalitiesToCheck,
                      study,
                    }).valid;
                    const isValidB = b.isValidMode({
                      modalities: modalitiesToCheck,
                      study,
                    }).valid;

                    return isValidB - isValidA;
                  })
                : appConfig.loadedModes
              ).map((mode, i) => {
                if (mode.hide) {
                  return null;
                }

                const { valid: isValidMode, description: invalidModeDescription } = mode.isValidMode({
                  modalities: modalitiesToCheck,
                  study,
                });

                if (isValidMode === null) {
                  return null;
                }

                const query = new URLSearchParams();
                if (filterValues.configUrl) {
                  query.append('configUrl', filterValues.configUrl);
                }
                query.append('StudyInstanceUIDs', studyInstanceUid);
                preserveQueryParameters(query);

                return (
                  mode.displayName && (
                    <Link
                      className={isValidMode ? '' : 'cursor-not-allowed'}
                      key={i}
                      to={`${mode.routeName}${dataPath || ''}?${query.toString()}`}
                      onClick={event => {
                        if (!isValidMode) {
                          event.preventDefault();
                        }
                      }}
                    >
                      <Button
                        type={ButtonEnums.type.primary}
                        size={ButtonEnums.size.small}
                        disabled={!isValidMode}
                        startIconTooltip={
                          !isValidMode ? (
                            <div className="font-inter flex w-[206px] whitespace-normal text-left text-xs font-normal text-white">
                              {invalidModeDescription}
                            </div>
                          ) : null
                        }
                        startIcon={
                          isValidMode ? (
                            <Icons.LaunchArrow className="!h-[20px] !w-[20px] text-black" />
                          ) : (
                            <Icons.LaunchInfo className="!h-[20px] !w-[20px] text-black" />
                          )
                        }
                        onClick={() => {}}
                        dataCY={`mode-${mode.routeName}-${studyInstanceUid}`}
                        className={isValidMode ? undefined : 'bg-[#222d44]'}
                      >
                        {mode.displayName}
                      </Button>
                    </Link>
                  )
                );
              })}
            </div>
          </StudyListExpandedRow>
        </div>
      );
    };

    const buildStudyRowData = study => {
      const studyInstanceUid = getStudyInstanceUid(study);
      const studyRowKey = getStudyGroupStudyKey(group.key, study);
      const isStudyExpanded = expandedStudyRows.includes(studyRowKey);
      const studyIdentifier = study.studyId || study.accession || '(empty)';
      const studyDate = getStudyDateLabel(study, t);
      const studyDescription = study.description || '(empty)';
      const studyModality = study.modalities || '';
      const studyInstances = Number(study.instances || 0);

      return {
        dataCY: `studyRow-${studyRowKey}`,
        clickableCY: studyRowKey,
        row: [
          {
            key: 'studyId',
            content: makeCopyTooltipCell(studyIdentifier),
            title: studyIdentifier,
            gridCol: 6,
          },
          {
            key: 'studyDate',
            content: studyDate,
            title: studyDate,
            gridCol: 6,
          },
          {
            key: 'description',
            content: makeCopyTooltipCell(studyDescription),
            title: studyDescription,
            gridCol: 5,
          },
          {
            key: 'modality',
            content: makeCopyTooltipCell(studyModality),
            title: studyModality,
            gridCol: 4,
          },
          {
            key: 'instances',
            content: studyInstances,
            title: `${studyInstances}`,
            gridCol: 3,
          },
        ],
        expandedContent: renderStudyExpandedContent(study),
        onClickRow: () =>
          setExpandedStudyRows(current =>
            isStudyExpanded ? current.filter(k => k !== studyRowKey) : [...current, studyRowKey]
          ),
        isExpanded: isStudyExpanded,
      };
    };

    return {
      dataCY: `studyGroup-${group.key}`,
      clickableCY: group.key,
      row: [
        {
          key: 'patientName',
          content: patientName ? makeCopyTooltipCell(patientName) : null,
          gridCol: 4,
        },
        {
          key: 'mrn',
          content: makeCopyTooltipCell(mrn),
          gridCol: 3,
        },
        {
          key: 'studyDate',
          content: (
            <>
              {(studyDateLabel || summaryTitle) && (
                <span className="mr-4">{studyDateLabel || summaryTitle}</span>
              )}
            </>
          ),
          title: studyDateLabel || summaryTitle,
          gridCol: 8,
        },
        {
          key: 'sex',
          content: makeCopyTooltipCell(sex),
          title: sex,
          gridCol: 2,
        },
        {
          key: 'age',
          content: makeCopyTooltipCell(age),
          title: age,
          gridCol: 2,
        },
        {
          key: 'instances',
          content: (
            <>
              <Icons.GroupLayers
                className={classnames('mr-2 inline-flex w-4', {
                  'text-primary': isExpanded,
                  'text-secondary-light': !isExpanded,
                })}
              />
              {instances}
            </>
          ),
          title: instances.toString(),
          gridCol: 5,
        },
      ],
      expandedContent: (
        <div className="bg-black px-3 pb-3 pt-0">
          {renderStudyListHeader(INNER_STUDY_COLUMNS)}
          <table className="w-full border-collapse text-white">
            <tbody data-cy={`studyList-${group.key}`}>
              {group.studies.map(study => (
                <StudyListTableRow
                  key={getStudyGroupStudyKey(group.key, study)}
                  tableData={buildStudyRowData(study)}
                />
              ))}
            </tbody>
          </table>
        </div>
      ),
      onClickRow: () =>
        setExpandedRows(current => (isExpanded ? current.filter(n => rowKey !== n) : [...current, rowKey])),
      isExpanded,
    };
  });

  const hasStudies = numOfStudies > 0;

  const AboutModal = customizationService.getCustomization(
    'ohif.aboutModal'
  ) as coreTypes.MenuComponentCustomization;
  const UserPreferencesModal = customizationService.getCustomization(
    'ohif.userPreferencesModal'
  ) as coreTypes.MenuComponentCustomization;

  const menuOptions = [
    {
      title: AboutModal?.menuTitle ?? t('Header:About'),
      icon: 'info',
      onClick: () =>
        show({
          content: AboutModal,
          title: AboutModal?.title ?? t('AboutModal:About OHIF Viewer'),
          containerClassName: AboutModal?.containerClassName ?? 'max-w-md',
        }),
    },
    {
      title: UserPreferencesModal.menuTitle ?? t('Header:Preferences'),
      icon: 'settings',
      onClick: () =>
        show({
          content: UserPreferencesModal as React.ComponentType,
          title: UserPreferencesModal.title ?? t('UserPreferencesModal:User preferences'),
          containerClassName:
            UserPreferencesModal?.containerClassName ?? 'flex max-w-4xl p-6 flex-col',
        }),
    },
  ];

  if (appConfig.oidc) {
    menuOptions.push({
      icon: 'power-off',
      title: t('Header:Logout'),
      onClick: () => {
        navigate(`/logout?redirect_uri=${encodeURIComponent(window.location.href)}`);
      },
    });
  }

  const LoadingIndicatorProgress = customizationService.getCustomization(
    'ui.loadingIndicatorProgress'
  );
  const effectiveSortBy = sortBy || (canSort ? 'studyDate' : '');
  const effectiveSortDirection = sortDirection || (canSort ? 'ascending' : 'none');
  const headerContent = (
    <div className="bg-black">
      {renderStudyListHeader(OUTER_STUDY_COLUMNS, {
        canSort,
        sortBy: effectiveSortBy,
        sortDirection: effectiveSortDirection,
        onSort: columnKey => {
          let nextSortDirection = 'descending';
          if (sortBy === columnKey) {
            if (sortDirection === 'ascending') {
              nextSortDirection = 'descending';
            } else if (sortDirection === 'descending') {
              nextSortDirection = 'ascending';
            }
          }

          setFilterValues({
            ...filterValues,
            sortBy: nextSortDirection ? columnKey : '',
            sortDirection: nextSortDirection,
          });
        },
      })}
      {renderStudyListFilterRow({
        filterValues,
        onChange: setFilterValues,
        clearFilters: () => setFilterValues(defaultFilterValues),
        isFiltering: isFiltering(filterValues, defaultFilterValues),
        clearFiltersLabel: t('ClearFilters'),
      })}
    </div>
  );

  return (
    <div className="flex h-screen flex-col bg-black text-white">
      <Header
        isSticky
        menuOptions={menuOptions}
        isReturnEnabled={false}
        WhiteLabeling={appConfig.whiteLabeling}
        showPatientInfo={PatientInfoVisibility.DISABLED}
      />
      <Onboarding />
      <InvestigationalUseDialog dialogConfiguration={appConfig?.investigationalUseDialog} />
      <div className="flex min-h-0 flex-1 overflow-hidden bg-black">
        <WorkListSidebar
          studies={studies}
          dataSource={dataSource}
          sidebarConfig={sidebarConfig}
          activeCategoryValues={normalizeCategoryValues(filterValues.categoryPath)}
          onSelectCategoryValues={handleSidebarSelection}
          isCollapsed={isSidebarCollapsed}
          onToggleCollapsed={() => setIsSidebarCollapsed(value => !value)}
        />
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {hasStudies ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <div className="min-h-0 flex-1 overflow-auto px-6 pb-4 pt-0">
                <StudyListTable
                  tableDataSource={tableDataSource}
                  numOfStudies={numOfStudies}
                  querying={querying}
                  filtersMeta={filtersMeta}
                  headerContent={headerContent}
                />
              </div>
              <div className="shrink-0 border-t border-white/10 bg-black px-4">
                <StudyListPagination
                  onChangePage={onPageNumberChange}
                  onChangePerPage={onResultsPerPageChange}
                  currentPage={pageNumber}
                  perPage={resultsPerPage}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center px-6">
              {appConfig.showLoadingIndicator && isLoadingData ? (
                <LoadingIndicatorProgress className={'h-full w-full bg-black'} />
              ) : (
                <EmptyStudies />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

WorkList.propTypes = {
  data: PropTypes.array.isRequired,
  dataSource: PropTypes.shape({
    query: PropTypes.object.isRequired,
    getConfig: PropTypes.func,
  }).isRequired,
  isLoadingData: PropTypes.bool.isRequired,
  servicesManager: PropTypes.object.isRequired,
};

const defaultFilterValues = {
  patientName: '',
  mrn: '',
  studyDate: {
    startDate: null,
    endDate: null,
  },
  sex: '',
  age: '',
  categoryPath: [],
  sortBy: '',
  sortDirection: 'none',
  pageNumber: 1,
  resultsPerPage: 25,
  datasources: '',
};

function _tryParseInt(str, defaultValue) {
  let retValue = defaultValue;
  if (str && str.length > 0) {
    if (!isNaN(str)) {
      retValue = parseInt(str);
    }
  }
  return retValue;
}

function _getQueryFilterValues(params) {
  const newParams = new URLSearchParams();
  for (const [key, value] of params) {
    newParams.set(key.toLowerCase(), value);
  }
  params = newParams;

  const queryFilterValues = {
    patientName: params.get('patientname'),
    mrn: params.get('mrn'),
    studyDate: {
      startDate: params.get('startdate') || null,
      endDate: params.get('enddate') || null,
    },
    sex: params.get('sex'),
    age: params.get('age'),
    categoryPath: params.get('categorypath') ? params.get('categorypath').split(',') : [],
    sortBy: params.get('sortby'),
    sortDirection: params.get('sortdirection'),
    pageNumber: _tryParseInt(params.get('pagenumber'), undefined),
    resultsPerPage: _tryParseInt(params.get('resultsperpage'), undefined),
    datasources: params.get('datasources'),
    configUrl: params.get('configurl'),
  };

  // Delete null/undefined keys
  Object.keys(queryFilterValues).forEach(
    key => queryFilterValues[key] == null && delete queryFilterValues[key]
  );

  return queryFilterValues;
}

function _sortStringDates(s1, s2, sortModifier) {
  // TODO: Delimiters are non-standard. Should we support them?
  const s1Date = moment(s1.date, ['YYYYMMDD', 'YYYY.MM.DD'], true);
  const s2Date = moment(s2.date, ['YYYYMMDD', 'YYYY.MM.DD'], true);

  if (s1Date.isValid() && s2Date.isValid()) {
    return (s1Date.toISOString() > s2Date.toISOString() ? 1 : -1) * sortModifier;
  } else if (s1Date.isValid()) {
    return sortModifier;
  } else if (s2Date.isValid()) {
    return -1 * sortModifier;
  }
}

export default WorkList;
