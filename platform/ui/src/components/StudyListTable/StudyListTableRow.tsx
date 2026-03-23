import React from 'react';
import PropTypes from 'prop-types';
import classnames from 'classnames';
import getGridWidthClass from '../../utils/getGridWidthClass';
import { Icons } from '@ohif/ui-next';

const StudyListTableRow = props => {
  const { tableData } = props;
  const { row, expandedContent, onClickRow, isExpanded, dataCY, clickableCY } = tableData;
  return (
    <>
      <tr
        className="select-none"
        data-cy={dataCY}
      >
        <td
          className={classnames('border-0 p-0 align-top', {
            'border-secondary-light bg-primary-dark border-b': isExpanded,
          })}
        >
          <div
            className={classnames(
              'w-full transition duration-300',
              {
                'border-primary-light hover:border-secondary-light mb-2 overflow-visible rounded border':
                  isExpanded,
              },
              {
                'border-transparent': !isExpanded,
              }
            )}
          >
            <div
              className={classnames(
                'flex w-full cursor-pointer flex-row transition duration-300',
                {
                  'bg-primary-dark hover:bg-secondary-main': !isExpanded,
                },
                { 'bg-secondary-dark': isExpanded }
              )}
              onClick={onClickRow}
              data-cy={clickableCY}
            >
              {row.map((cell, index) => {
                const { content, title, gridCol } = cell;
                return (
                  <div
                    key={index}
                    className={classnames(
                      'flex min-w-0 items-center px-4 py-2 text-base',
                      { 'border-secondary-light border-b': !isExpanded },
                      getGridWidthClass(gridCol) || ''
                    )}
                    title={title}
                  >
                    {index === 0 && (
                      <div className="mr-4 shrink-0">
                        {isExpanded ? (
                          <Icons.ChevronOpen className="-mt-1 inline-flex" />
                        ) : (
                          <Icons.ChevronClosed className="-mt-1 inline-flex rotate-180" />
                        )}
                      </div>
                    )}
                    <div className="min-w-0 truncate">{content}</div>
                  </div>
                );
              })}
            </div>
            {isExpanded && <div className="w-full select-text bg-black">{expandedContent}</div>}
          </div>
        </td>
      </tr>
    </>
  );
};

StudyListTableRow.propTypes = {
  tableData: PropTypes.shape({
    /** A table row represented by an array of "cell" objects */
    row: PropTypes.arrayOf(
      PropTypes.shape({
        key: PropTypes.string.isRequired,
        /** Optional content to render in row's cell */
        content: PropTypes.node,
        /** Title attribute to use for provided content */
        title: PropTypes.string,
        gridCol: PropTypes.number.isRequired,
      })
    ).isRequired,
    expandedContent: PropTypes.node.isRequired,
    onClickRow: PropTypes.func.isRequired,
    isExpanded: PropTypes.bool.isRequired,
    dataCY: PropTypes.string,
    clickableCY: PropTypes.string,
  }),
};

export default StudyListTableRow;
