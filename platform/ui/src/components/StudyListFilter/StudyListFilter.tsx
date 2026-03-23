import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import classnames from 'classnames';
import { useTranslation } from 'react-i18next';

import LegacyButton from '../LegacyButton';
import Typography from '../Typography';
import InputGroup from '../InputGroup';
import { Icons } from '@ohif/ui-next';

const ACCESS_CONTROL_OPTIONS = [
  { value: 'CRYOABLATION', label: 'CRYOABLATION' },
  { value: 'CHEST_CT', label: 'CHEST_CT' },
  { value: 'PULMONARY_NODULES', label: 'PULMONARY_NODULES' },
];

const StudyListFilter = ({
  filtersMeta,
  filterValues,
  onChange,
  clearFilters,
  isFiltering,
  numOfStudies,
  onUploadClick,
  getDataSourceConfigurationComponent,
}) => {
  const { t } = useTranslation('StudyList');
  const { sortBy, sortDirection } = filterValues;
  const filterSorting = { sortBy, sortDirection };
  const setFilterSorting = sortingValues => {
    onChange({
      ...filterValues,
      ...sortingValues,
    });
  };
  const isSortingEnabled = numOfStudies > 0 && numOfStudies <= 100;

  const accessControlValue = Array.isArray(filterValues.accessControlID)
    ? filterValues.accessControlID.filter(Boolean)
    : [];
  const [isAccessControlOpen, setIsAccessControlOpen] = useState(false);
  const accessControlPopoverRef = useRef(null);

  useEffect(() => {
    const handlePointerDown = event => {
      if (!accessControlPopoverRef.current) {
        return;
      }

      if (!accessControlPopoverRef.current.contains(event.target)) {
        setIsAccessControlOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, []);

  const accessControlLabels = accessControlValue
    .map(value => ACCESS_CONTROL_OPTIONS.find(option => option.value === value)?.label || value)
    .filter(Boolean);

  const handleAccessControlChange = newValues => {
    onChange({
      ...filterValues,
      accessControlID: Array.isArray(newValues) ? newValues : [],
    });
  };

  const toggleAccessControlValue = value => {
    const nextValues = accessControlValue.includes(value)
      ? accessControlValue.filter(selectedValue => selectedValue !== value)
      : [...accessControlValue, value];

    handleAccessControlChange(nextValues);
  };

  const clearAccessControlValues = () => {
    handleAccessControlChange([]);
  };

  return (
    <React.Fragment>
      <div>
        <div className="bg-black">
          <div className="container relative mx-auto flex flex-col pt-5">
            <div className="mb-5 flex flex-row justify-between">
              <div className="flex min-w-[1px] shrink flex-row items-center gap-6">
                <Typography
                  variant="h6"
                  className="text-white"
                >
                  {t('StudyList')}
                </Typography>
                {getDataSourceConfigurationComponent && getDataSourceConfigurationComponent()}
                {onUploadClick && (
                  <div
                    className="text-primary-active flex cursor-pointer items-center gap-2 self-center text-lg font-semibold"
                    onClick={onUploadClick}
                  >
                    <Icons.Upload />
                    <span>{t('Upload')}</span>
                  </div>
                )}
              </div>
              <div className="flex h-[34px] flex-row items-center">
                {isFiltering && (
                  <LegacyButton
                    rounded="full"
                    variant="outlined"
                    color="primaryActive"
                    border="primaryActive"
                    className="mx-8"
                    startIcon={<Icons.Cancel />}
                    onClick={clearFilters}
                  >
                    {t('ClearFilters')}
                  </LegacyButton>
                )}

                <Typography
                  variant="h6"
                  className="mr-2"
                  data-cy={'num-studies'}
                >
                  {numOfStudies > 100 ? '>100' : numOfStudies}
                </Typography>
                <Typography
                  variant="h6"
                  className="text-primary-light"
                >
                  {`${t('Studies')} `}
                </Typography>
              </div>
            </div>
          </div>

          <div className="container relative mx-auto px-4 pb-4">
            <div className="flex items-start gap-4">
              <Typography
                variant="h6"
                className="pt-2 text-white"
              >
                {'分类标签'}
              </Typography>

              <div
                ref={accessControlPopoverRef}
                className="relative"
              >
                <button
                  type="button"
                  className={classnames(
                    'flex h-10 w-[340px] max-w-full items-center justify-between gap-3 rounded border px-4 text-left text-sm transition focus:outline-none',
                    isAccessControlOpen
                      ? 'border-primary-light bg-secondary-dark'
                      : 'border-primary-active bg-black hover:border-primary-light'
                  )}
                  onClick={() => setIsAccessControlOpen(open => !open)}
                >
                  <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
                    {accessControlLabels.length ? (
                      <>
                        {accessControlLabels.slice(0, 2).map(label => (
                          <span
                            key={label}
                            className="inline-flex max-w-[120px] items-center rounded-full bg-primary-main/20 px-2 py-1 text-xs font-medium text-primary-light"
                          >
                            <span className="truncate">{label}</span>
                          </span>
                        ))}
                        {accessControlLabels.length > 2 && (
                          <span className="inline-flex items-center rounded-full border border-primary-active/60 px-2 py-1 text-xs text-primary-light">
                            +{accessControlLabels.length - 2}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="truncate text-secondary-light">请选择分类标签</span>
                    )}
                  </div>
                  <Icons.ChevronDown
                    className={classnames('h-4 w-4 shrink-0 transition-transform', {
                      'rotate-180': isAccessControlOpen,
                    })}
                  />
                </button>

                {isAccessControlOpen && (
                  <div className="absolute left-0 top-full z-50 mt-2 w-[360px] rounded border border-primary-active bg-black p-3 shadow-[0_16px_40px_rgba(0,0,0,0.45)]">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <Typography
                        variant="h6"
                        className="text-base text-white"
                      >
                        分类标签
                      </Typography>
                      <button
                        type="button"
                        className="text-primary-light text-sm hover:underline"
                        onClick={clearAccessControlValues}
                      >
                        清空
                      </button>
                    </div>

                    <div className="space-y-2">
                      {ACCESS_CONTROL_OPTIONS.map(option => {
                        const isSelected = accessControlValue.includes(option.value);

                        return (
                          <button
                            key={option.value}
                            type="button"
                            className={classnames(
                              'flex w-full items-center gap-3 rounded px-2 py-2 text-left transition',
                              isSelected
                                ? 'bg-primary-main/15 text-white'
                                : 'text-secondary-light hover:bg-secondary-dark/50 hover:text-white'
                            )}
                            onClick={() => toggleAccessControlValue(option.value)}
                          >
                            <span
                              className={classnames(
                                'flex h-4 w-4 items-center justify-center rounded border',
                                isSelected
                                  ? 'border-primary-active bg-primary-active text-black'
                                  : 'border-secondary-light'
                              )}
                            >
                              {isSelected ? (
                                <Icons.ByName name="checkbox-active" />
                              ) : (
                                <Icons.ByName name="checkbox-default" />
                              )}
                            </span>
                            <span className="flex-1">{option.label}</span>
                          </button>
                        );
                      })}
                    </div>

                    <div className="mt-3 flex items-center justify-between border-t border-secondary-light pt-3">
                      <span className="text-xs text-secondary-light">{accessControlLabels.length} 已选</span>
                      <button
                        type="button"
                        className="text-primary-light text-sm hover:underline"
                        onClick={() => setIsAccessControlOpen(false)}
                      >
                        完成
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="sticky -top-1 z-10 w-full border-b-4 border-black bg-black">
        <div className="container relative m-auto bg-primary-dark pt-3 pb-3">
          <InputGroup
            inputMeta={filtersMeta}
            values={filterValues}
            onValuesChange={onChange}
            sorting={filterSorting}
            onSortingChange={setFilterSorting}
            isSortingEnabled={isSortingEnabled}
          />
        </div>
        {numOfStudies > 100 && (
          <div className="container m-auto">
            <div className="bg-primary-main rounded-b py-1 text-center text-base">
              <p className="text-white">
                {t('Filter list to 100 studies or less to enable sorting')}
              </p>
            </div>
          </div>
        )}
      </div>
    </React.Fragment>
  );
};

StudyListFilter.propTypes = {
  filtersMeta: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string.isRequired,
      displayName: PropTypes.string.isRequired,
      inputType: PropTypes.oneOf(['Text', 'MultiSelect', 'DateRange', 'None']).isRequired,
      isSortable: PropTypes.bool.isRequired,
      gridCol: PropTypes.oneOf([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]).isRequired,
      option: PropTypes.arrayOf(
        PropTypes.shape({
          value: PropTypes.string,
          label: PropTypes.string,
        })
      ),
    })
  ).isRequired,
  filterValues: PropTypes.object.isRequired,
  numOfStudies: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired,
  clearFilters: PropTypes.func.isRequired,
  isFiltering: PropTypes.bool.isRequired,
  onUploadClick: PropTypes.func,
  getDataSourceConfigurationComponent: PropTypes.func,
};

export default StudyListFilter;
