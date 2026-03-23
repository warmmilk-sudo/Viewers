import React, { useCallback, useState } from 'react';
import { ReactElement } from 'react';
import Dropzone from 'react-dropzone';
import PropTypes from 'prop-types';
import classNames from 'classnames';
import DicomFileUploader from '../../utils/DicomFileUploader';
import DicomUploadProgress from './DicomUploadProgress';
import { Button } from '@ohif/ui-next';

const ACCESS_CONTROL_ID_OPTIONS = ['CRYOABLATION', 'CHEST_CT', 'PULMONARY_NODULES'];

type DicomUploadProps = {
  dataSource;
  onComplete: () => void;
  onStarted: () => void;
};

function DicomUpload({ dataSource, onComplete, onStarted }: DicomUploadProps): ReactElement {
  const baseClassNames =
    'min-h-[375px] flex flex-col bg-background select-none rounded-lg overflow-hidden';
  const [dicomFileUploaderArr, setDicomFileUploaderArr] = useState([]);
  const [accessControlID, setAccessControlID] = useState('');
  const normalizedAccessControlID = accessControlID.trim();
  const isClassificationSelected = normalizedAccessControlID.length > 0;

  const onDrop = useCallback(
    async acceptedFiles => {
      if (!isClassificationSelected) {
        return;
      }

      onStarted();
      setDicomFileUploaderArr(
        acceptedFiles.map(file => new DicomFileUploader(file, dataSource, normalizedAccessControlID))
      );
    },
    [dataSource, isClassificationSelected, normalizedAccessControlID, onStarted]
  );

  const getDropZoneComponent = (): ReactElement => {
    return (
      <Dropzone
        onDrop={acceptedFiles => {
          onDrop(acceptedFiles);
        }}
        noClick
        disabled={!isClassificationSelected}
      >
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className="m-5 flex h-full flex-col items-center justify-center rounded-2xl border"
            style={{ borderColor: 'hsl(var(--muted-foreground) / 0.25)' }}
          >
            <div className="flex w-full max-w-md flex-col gap-2 px-6 pt-6">
              <label
                className="text-foreground text-base font-medium"
                htmlFor="dicom-upload-access-control-id"
              >
                {'分类标签（Access Control ID）'}
              </label>
              <input
                id="dicom-upload-access-control-id"
                list="dicom-upload-access-control-id-options"
                value={accessControlID}
                onChange={event => setAccessControlID(event.target.value)}
                placeholder="请输入或选择分类标签"
                className="border-input bg-background text-foreground rounded-md border px-3 py-2 text-base outline-none"
              />
              <datalist id="dicom-upload-access-control-id-options">
                {ACCESS_CONTROL_ID_OPTIONS.map(option => (
                  <option
                    key={option}
                    value={option}
                  />
                ))}
              </datalist>
              <div className="text-muted-foreground text-sm">
                {'可输入新的分类标签，再开始上传。'}
              </div>
            </div>
            <div className="mt-8 flex gap-2">
              <Dropzone
                onDrop={onDrop}
                noDrag
                disabled={!isClassificationSelected}
              >
                {({ getRootProps, getInputProps }) => (
                  <div {...getRootProps()}>
                    <Button
                      variant="default"
                      size="lg"
                      disabled={!isClassificationSelected}
                      onClick={() => {}}
                    >
                      {'Add files'}
                      <input
                        {...getInputProps()}
                        style={{ display: 'none' }}
                      />
                    </Button>
                  </div>
                )}
              </Dropzone>
              <Dropzone
                onDrop={onDrop}
                noDrag
                disabled={!isClassificationSelected}
              >
                {({ getRootProps, getInputProps }) => (
                  <div {...getRootProps()}>
                    <Button
                      variant="secondary"
                      size="lg"
                      disabled={!isClassificationSelected}
                      onClick={() => {}}
                    >
                      {'Add folder'}
                      <input
                        {...getInputProps()}
                        webkitdirectory="true"
                        mozdirectory="true"
                        style={{ display: 'none' }}
                      />
                    </Button>
                  </div>
                )}
              </Dropzone>
            </div>
            <div className="text-foreground pt-6 text-base">or drag images or folders here</div>
            <div className="text-muted-foreground pt-1 text-base">(DICOM files supported)</div>
          </div>
        )}
      </Dropzone>
    );
  };

  return (
    <>
      {dicomFileUploaderArr.length ? (
        <div className={classNames('h-[calc(100vh-300px)]', baseClassNames)}>
          <DicomUploadProgress
            dicomFileUploaderArr={Array.from(dicomFileUploaderArr)}
            onComplete={onComplete}
          />
        </div>
      ) : (
        <div className={classNames('h-[480px]', baseClassNames)}>{getDropZoneComponent()}</div>
      )}
    </>
  );
}

DicomUpload.propTypes = {
  dataSource: PropTypes.object.isRequired,
  onComplete: PropTypes.func.isRequired,
  onStarted: PropTypes.func.isRequired,
};

export default DicomUpload;
