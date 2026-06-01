import React, { useState, useEffect, useCallback, useRef } from 'react';
import { X } from 'lucide-react';

interface TetrisGameProps {
  isOpen: boolean;
  onClose: () => void;
}

// 游戏板大小
const BOARD_WIDTH = 10;
const BOARD_HEIGHT = 20;

// 俄罗斯方块形状
const TETROMINOS = {
  I: [
    [[1, 1, 1, 1]]
  ],
  O: [
    [[1, 1], [1, 1]]
  ],
  T: [
    [[0, 1, 0], [1, 1, 1]]
  ],
  S: [
    [[0, 1, 1], [1, 1, 0]]
  ],
  Z: [
    [[1, 1, 0], [0, 1, 1]]
  ],
  J: [
    [[1, 0, 0], [1, 1, 1]]
  ],
  L: [
    [[0, 0, 1], [1, 1, 1]]
  ]
};

type TetrominoType = keyof typeof TETROMINOS;

interface Position {
  x: number;
  y: number;
}

interface Tetromino {
  shape: number[][];
  type: TetrominoType;
  position: Position;
}

const createBoard = () => Array(BOARD_HEIGHT).fill(null).map(() => Array(BOARD_WIDTH).fill(0));

const randomTetromino = (): TetrominoType => {
  const types: TetrominoType[] = ['I', 'O', 'T', 'S', 'Z', 'J', 'L'];
  return types[Math.floor(Math.random() * types.length)];
};

const createTetromino = (type: TetrominoType): Tetromino => ({
  shape: TETROMINOS[type][0],
  type,
  position: { x: Math.floor(BOARD_WIDTH / 2) - 1, y: 0 }
});

export const TetrisGame: React.FC<TetrisGameProps> = ({ isOpen, onClose }) => {
  const [board, setBoard] = useState(createBoard());
  const [currentPiece, setCurrentPiece] = useState<Tetromino | null>(null);
  const [nextPiece, setNextPiece] = useState<Tetromino | null>(null);
  const [score, setScore] = useState(0);
  const [level, setLevel] = useState(1);
  const [lines, setLines] = useState(0);
  const [gameOver, setGameOver] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const gameLoopRef = useRef<NodeJS.Timeout | null>(null);
  const dropTimeRef = useRef<number>(1000);

  // 检查碰撞
  const checkCollision = useCallback((piece: Tetromino, board: number[][], position: Position): boolean => {
    for (let y = 0; y < piece.shape.length; y++) {
      for (let x = 0; x < piece.shape[y].length; x++) {
        if (piece.shape[y][x]) {
          const newX = position.x + x;
          const newY = position.y + y;
          
          if (
            newX < 0 ||
            newX >= BOARD_WIDTH ||
            newY >= BOARD_HEIGHT ||
            (newY >= 0 && board[newY][newX])
          ) {
            return true;
          }
        }
      }
    }
    return false;
  }, []);

  // 旋转方块
  const rotatePiece = useCallback((piece: Tetromino): Tetromino => {
    const rotated = piece.shape[0].map((_, i) =>
      piece.shape.map(row => row[i]).reverse()
    );
    return { ...piece, shape: rotated };
  }, []);

  // 清除完整行
  const clearLines = useCallback((board: number[][]): { newBoard: number[][], cleared: number } => {
    const newBoard = board.filter(row => !row.every(cell => cell));
    const cleared = BOARD_HEIGHT - newBoard.length;
    while (newBoard.length < BOARD_HEIGHT) {
      newBoard.unshift(Array(BOARD_WIDTH).fill(0));
    }
    return { newBoard, cleared };
  }, []);

  // 放置方块
  const placePiece = useCallback(() => {
    if (!currentPiece) return;

    const newBoard = board.map(row => [...row]);
    
    for (let y = 0; y < currentPiece.shape.length; y++) {
      for (let x = 0; x < currentPiece.shape[y].length; x++) {
        if (currentPiece.shape[y][x]) {
          const boardY = currentPiece.position.y + y;
          const boardX = currentPiece.position.x + x;
          if (boardY >= 0) {
            newBoard[boardY][boardX] = 1;
          }
        }
      }
    }

    const { newBoard: clearedBoard, cleared } = clearLines(newBoard);
    setBoard(clearedBoard);
    
    if (cleared > 0) {
      setLines(prev => prev + cleared);
      setScore(prev => prev + cleared * 100 * level);
      setLevel(prev => Math.floor((lines + cleared) / 10) + 1);
      dropTimeRef.current = Math.max(100, 1000 - (level - 1) * 100);
    }

    // 生成新方块
    const newType = nextPiece ? nextPiece.type : randomTetromino();
    const newNextType = randomTetromino();
    setCurrentPiece(createTetromino(newType));
    setNextPiece(createTetromino(newNextType));

    // 检查游戏结束
    const newPiece = createTetromino(newType);
    if (checkCollision(newPiece, clearedBoard, newPiece.position)) {
      setGameOver(true);
      if (gameLoopRef.current) {
        clearInterval(gameLoopRef.current);
      }
    }
  }, [currentPiece, board, nextPiece, level, lines, checkCollision, clearLines]);

  // 移动方块
  const movePiece = useCallback((direction: 'left' | 'right' | 'down') => {
    if (!currentPiece || gameOver || isPaused) return;

    const newPosition = { ...currentPiece.position };
    if (direction === 'left') newPosition.x -= 1;
    else if (direction === 'right') newPosition.x += 1;
    else if (direction === 'down') newPosition.y += 1;

    if (!checkCollision(currentPiece, board, newPosition)) {
      setCurrentPiece({ ...currentPiece, position: newPosition });
    } else if (direction === 'down') {
      placePiece();
    }
  }, [currentPiece, board, gameOver, isPaused, checkCollision, placePiece]);

  // 键盘控制
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyPress = (e: KeyboardEvent) => {
      if (gameOver || isPaused) return;

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          movePiece('left');
          break;
        case 'ArrowRight':
          e.preventDefault();
          movePiece('right');
          break;
        case 'ArrowDown':
          e.preventDefault();
          movePiece('down');
          break;
        case 'ArrowUp':
        case 'w':
        case 'W':
          e.preventDefault();
          if (currentPiece) {
            const rotated = rotatePiece(currentPiece);
            if (!checkCollision(rotated, board, rotated.position)) {
              setCurrentPiece(rotated);
            }
          }
          break;
        case ' ':
          e.preventDefault();
          setIsPaused(prev => !prev);
          break;
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [isOpen, gameOver, isPaused, currentPiece, board, movePiece, rotatePiece, checkCollision]);

  // 游戏循环
  useEffect(() => {
    if (!isOpen || gameOver || isPaused) {
      if (gameLoopRef.current) {
        clearInterval(gameLoopRef.current);
        gameLoopRef.current = null;
      }
      return;
    }

    gameLoopRef.current = setInterval(() => {
      movePiece('down');
    }, dropTimeRef.current);

    return () => {
      if (gameLoopRef.current) {
        clearInterval(gameLoopRef.current);
      }
    };
  }, [isOpen, gameOver, isPaused, movePiece]);

  // 初始化游戏
  useEffect(() => {
    if (isOpen && !currentPiece) {
      const type1 = randomTetromino();
      const type2 = randomTetromino();
      setCurrentPiece(createTetromino(type1));
      setNextPiece(createTetromino(type2));
      setBoard(createBoard());
      setScore(0);
      setLevel(1);
      setLines(0);
      setGameOver(false);
      setIsPaused(false);
      dropTimeRef.current = 1000;
    }
  }, [isOpen, currentPiece]);

  // 渲染游戏板
  const renderBoard = () => {
    const displayBoard = board.map(row => [...row]);
    
    if (currentPiece) {
      for (let y = 0; y < currentPiece.shape.length; y++) {
        for (let x = 0; x < currentPiece.shape[y].length; x++) {
          if (currentPiece.shape[y][x]) {
            const boardY = currentPiece.position.y + y;
            const boardX = currentPiece.position.x + x;
            if (boardY >= 0 && boardY < BOARD_HEIGHT && boardX >= 0 && boardX < BOARD_WIDTH) {
              displayBoard[boardY][boardX] = 2; // 2表示当前方块
            }
          }
        }
      }
    }

    return displayBoard;
  };

  // 渲染下一个方块
  const renderNextPiece = () => {
    if (!nextPiece) return null;
    
    return (
      <div className="flex flex-col items-center">
        {nextPiece.shape.map((row, y) => (
          <div key={y} className="flex">
            {row.map((cell, x) => (
              <div
                key={x}
                className={`w-4 h-4 border ${
                  cell ? 'bg-blue-500 border-blue-600' : 'bg-transparent border-transparent'
                }`}
              />
            ))}
          </div>
        ))}
      </div>
    );
  };

  if (!isOpen) return null;

  const displayBoard = renderBoard();

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-2xl">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-2xl font-bold">俄罗斯方块</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X size={24} />
          </button>
        </div>

        <div className="flex gap-6">
          {/* 游戏板 */}
          <div className="flex-1">
            <div className="border-2 border-gray-800 bg-gray-900 p-2 inline-block">
              {displayBoard.map((row, y) => (
                <div key={y} className="flex">
                  {row.map((cell, x) => (
                    <div
                      key={`${y}-${x}`}
                      className={`w-6 h-6 border border-gray-700 ${
                        cell === 1
                          ? 'bg-yellow-500 border-yellow-600'
                          : cell === 2
                          ? 'bg-blue-500 border-blue-600'
                          : 'bg-gray-800'
                      }`}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>

          {/* 信息面板 */}
          <div className="w-48 space-y-4">
            <div>
              <h3 className="font-semibold mb-2">下一个</h3>
              <div className="bg-gray-100 p-3 rounded">
                {renderNextPiece()}
              </div>
            </div>

            <div className="space-y-2">
              <div>
                <span className="font-semibold">分数: </span>
                <span>{score}</span>
              </div>
              <div>
                <span className="font-semibold">等级: </span>
                <span>{level}</span>
              </div>
              <div>
                <span className="font-semibold">消除行数: </span>
                <span>{lines}</span>
              </div>
            </div>

            {gameOver && (
              <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
                <p className="font-bold">游戏结束！</p>
                <button
                  onClick={() => {
                    setCurrentPiece(null);
                    setNextPiece(null);
                    setGameOver(false);
                  }}
                  className="mt-2 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
                >
                  重新开始
                </button>
              </div>
            )}

            {isPaused && !gameOver && (
              <div className="bg-yellow-100 border border-yellow-400 text-yellow-700 px-4 py-3 rounded">
                <p className="font-bold">游戏暂停</p>
                <p className="text-sm mt-1">按空格键继续</p>
              </div>
            )}

            <div className="text-sm text-gray-600 space-y-1">
              <p><strong>操作说明:</strong></p>
              <p>← → : 左右移动</p>
              <p>↓ : 快速下降</p>
              <p>↑ / W : 旋转</p>
              <p>空格 : 暂停/继续</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
