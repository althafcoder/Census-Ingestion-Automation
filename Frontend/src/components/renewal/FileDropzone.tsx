import { useRef, useState, type DragEvent } from "react";
import { FileText, X, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FileDropzoneProps {
  file?: File | null;
  onFileChange?: (file: File | null) => void;
  files?: File[];
  onFilesChange?: (files: File[]) => void;
  multiple?: boolean;
  accept: string;
  acceptLabel: string;
  maxSizeMB?: number;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export function FileDropzone({
  file,
  onFileChange,
  files = [],
  onFilesChange,
  multiple = false,
  accept,
  acceptLabel,
  maxSizeMB = 50,
}: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFiles = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    
    if (!multiple) {
      const f = fileList[0];
      if (f.size > maxSizeMB * 1024 * 1024) {
        setError(`File exceeds ${maxSizeMB}MB limit`);
        return;
      }
      setError(null);
      if (onFileChange) onFileChange(f);
      return;
    }

    // Multiple files
    const validFiles: File[] = [];
    for (let i = 0; i < fileList.length; i++) {
      if (fileList[i].size > maxSizeMB * 1024 * 1024) {
        setError(`One or more files exceed ${maxSizeMB}MB limit`);
        return;
      }
      validFiles.push(fileList[i]);
    }
    setError(null);
    if (onFilesChange) onFilesChange([...files, ...validFiles]);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  const removeFile = (index: number) => {
    if (onFilesChange) {
      const newFiles = [...files];
      newFiles.splice(index, 1);
      onFilesChange(newFiles);
    }
  };

  const hasFiles = (multiple && files.length > 0) || (!multiple && file);

  if (hasFiles && !multiple && file) {
    return (
      <div className="rounded-lg border border-border bg-muted/40 p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileText className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
            <p className="text-xs text-muted-foreground">{formatSize(file.size)}</p>
          </div>
          <button
            type="button"
            onClick={() => onFileChange && onFileChange(null)}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label="Remove file"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {multiple && files.length > 0 && (
        <div className="space-y-2">
          {files.map((f, i) => (
            <div key={i} className="rounded-lg border border-border bg-muted/40 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <FileText className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">{f.name}</p>
                  <p className="text-xs text-muted-foreground">{formatSize(f.size)}</p>
                </div>
                <button
                  type="button"
                  onClick={() => removeFile(i)}
                  className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  aria-label="Remove file"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragOver ? "border-primary bg-primary/5" : "border-border hover:border-primary/50 hover:bg-muted/30"
        }`}
      >
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
          <UploadCloud className="h-5 w-5" />
        </div>
        <p className="text-sm font-medium text-foreground">Drag &amp; drop your file{multiple ? "s" : ""} here</p>
        <p className="mt-1 text-xs text-muted-foreground">
          or click to browse &middot; {acceptLabel} &middot; max {maxSizeMB}MB
        </p>
        <Button
          type="button"
          size="sm"
          className="mt-4"
          onClick={(e) => {
            e.stopPropagation();
            inputRef.current?.click();
          }}
        >
          Select File{multiple ? "s" : ""}
        </Button>
        {error && <p className="mt-3 text-xs text-destructive">{error}</p>}
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>
    </div>
  );
}
