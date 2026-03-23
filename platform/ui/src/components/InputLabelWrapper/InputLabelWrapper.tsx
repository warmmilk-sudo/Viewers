import React, { useState } from 'react';
import PropTypes from 'prop-types';
import classnames from 'classnames';
import { Icons } from '@ohif/ui-next';

const baseLabelClassName = 'flex flex-col flex-1 text-white text-lg select-none';
const spanClassName = 'flex flex-row items-center cursor-pointer focus:outline-none';

const sortIconMap = {
  descending: () => <Icons.SortingDescending className="text-primary-main mx-2 w-2" />,
  ascending: () => <Icons.SortingAscending className="text-primary-main mx-2 w-2" />,
  none: () => <Icons.Sorting className="text-primary-main mx-2 w-2" />,
};

const InputLabelWrapper = ({
  label,
  isSortable,
  sortDirection,
  onLabelClick,
  className = '',
  children,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  const onClickHandler = e => {
    if (isSortable) {
      onLabelClick(e);
    }

    setIsExpanded(true);
  };

  const onKeyDownHandler = e => {
    if (e.key !== 'Enter' && e.key !== ' ') {
      return;
    }

    e.preventDefault();
    onClickHandler(e);
  };

  return (
    <label className={classnames(baseLabelClassName, className)}>
      <span
        role="button"
        className={spanClassName}
        onClick={onClickHandler}
        onKeyDown={onKeyDownHandler}
        tabIndex="0"
      >
        {label}
        {isSortable && sortIconMap[sortDirection]()}
      </span>
      {isExpanded ? <span>{children}</span> : null}
    </label>
  );
};

InputLabelWrapper.propTypes = {
  label: PropTypes.string.isRequired,
  isSortable: PropTypes.bool.isRequired,
  sortDirection: PropTypes.oneOf(['ascending', 'descending', 'none']).isRequired,
  onLabelClick: PropTypes.func.isRequired,
  className: PropTypes.string,
  children: PropTypes.node,
};

export default InputLabelWrapper;
