
import os
from google.colab import drive
drive.mount('/content/drive')

os.chdir('/content/drive/My Drive/TechVidvan/Sentiment')
# !ls

# !pip uninstall -y torchtext
# !pip install torchtext==0.6.0

import random
import torch
from torchtext import data
from torchtext import datasets

seed = 42

torch.manual_seed(seed)
torch.backends.cudnn.deterministic = True
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

txt = data.Field(tokenize = 'spacy',
                  tokenizer_language = 'en_core_web_sm',
                  include_lengths = True)

labels = data.LabelField(dtype = torch.float)

train_data, test_data = datasets.IMDB.splits(txt, labels)

train_data, valid_data = train_data.split(random_state = random.seed(seed))

num_words = 25_000

txt.build_vocab(train_data, 
                 max_size = num_words, 
                 vectors = "glove.6B.100d", 
                 unk_init = torch.Tensor.normal_)

labels.build_vocab(train_data)

btch_size = 64

train_itr, valid_itr, test_itr = data.BucketIterator.splits(
    (train_data, valid_data, test_data), 
    batch_size = btch_size,
    sort_within_batch = True,
    device = device)

import torch.nn as nn

class RNN(nn.Module):
    def __init__(self, word_limit, dimension_embedding, dimension_hidden, dimension_output, num_layers, 
                 bidirectional, dropout, pad_idx):
        
        super().__init__()
        
        self.embedding = nn.Embedding(word_limit, dimension_embedding, padding_idx = pad_idx)
        
        self.rnn = nn.LSTM(dimension_embedding, 
                           dimension_hidden, 
                           num_layers=num_layers, 
                           bidirectional=bidirectional, 
                           dropout=dropout)
        
        self.fc = nn.Linear(dimension_hidden * 2, dimension_output)
        
        self.dropout = nn.Dropout(dropout)
        
    def forward(self, text, len_txt):
        
        
        embedded = self.dropout(self.embedding(text))
               

        packed_embedded = nn.utils.rnn.pack_padded_sequence(embedded, len_txt.to('cpu'))
        
        packed_output, (hidden, cell) = self.rnn(packed_embedded)
        
        output, output_lengths = nn.utils.rnn.pad_packed_sequence(packed_output)

        
        hidden = self.dropout(torch.cat((hidden[-2,:,:], hidden[-1,:,:]), dim = 1))
                            
        return self.fc(hidden)

dimension_input = len(txt.vocab)
dimension_embedding = 100
dimension_hddn = 256
dimension_out = 1
layers = 2
bidirectional = True
droupout = 0.5
idx_pad = txt.vocab.stoi[txt.pad_token]

model = RNN(dimension_input, 
            dimension_embedding, 
            dimension_hddn, 
            dimension_out, 
            layers, 
            bidirectional, 
            droupout, 
            idx_pad)

def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

print(f'The model has {count_parameters(model):,} trainable parameters')

pretrained_embeddings = txt.vocab.vectors

print(pretrained_embeddings.shape)

model.embedding.weight.data.copy_(pretrained_embeddings)

unique_id = txt.vocab.stoi[txt.unk_token]

model.embedding.weight.data[unique_id] = torch.zeros(dimension_embedding)
model.embedding.weight.data[idx_pad] = torch.zeros(dimension_embedding)

print(model.embedding.weight.data)

import torch.optim as optim

optimizer = optim.Adam(model.parameters())

criterion = nn.BCEWithLogitsLoss()

model = model.to(device)
criterion = criterion.to(device)

def bin_acc(preds, y):
   
    predictions = torch.round(torch.sigmoid(preds))
    correct = (predictions == y).float() 
    acc = correct.sum() / len(correct)
    return acc

def train(model, itr, optimizer, criterion):
    
    epoch_loss = 0
    epoch_acc = 0
    
    model.train()
    
    for i in itr:
        
        optimizer.zero_grad()
        
        text, len_txt = i.text
        
        predictions = model(text, len_txt).squeeze(1)
        
        loss = criterion(predictions, i.label)
        
        acc = bin_acc(predictions, i.label)
        
        loss.backward()
        
        optimizer.step()
        
        epoch_loss += loss.item()
        epoch_acc += acc.item()
        
    return epoch_loss / len(itr), epoch_acc / len(itr)

def evaluate(model, itr, criterion):
    
    epoch_loss = 0
    epoch_acc = 0
    
    model.eval()
    
    with torch.no_grad():
    
        for i in itr:

            text, len_txt = i.text
            
            predictions = model(text, len_txt).squeeze(1)
            
            loss = criterion(predictions, i.label)
            
            acc = bin_acc(predictions, i.label)

            epoch_loss += loss.item()
            epoch_acc += acc.item()
        
    return epoch_loss / len(itr), epoch_acc / len(itr)

import time

def epoch_time(start_time, end_time):
    used_time = end_time - start_time
    used_mins = int(used_time / 60)
    used_secs = int(used_time - (used_mins * 60))
    return used_mins, used_secs

num_epochs = 5

best_valid_loss = float('inf')

for epoch in range(num_epochs):

    start_time = time.time()
    
    train_loss, train_acc = train(model, train_itr, optimizer, criterion)
    valid_loss, valid_acc = evaluate(model, valid_itr, criterion)
    
    end_time = time.time()

    epoch_mins, epoch_secs = epoch_time(start_time, end_time)
    
    if valid_loss < best_valid_loss:
        best_valid_loss = valid_loss
        torch.save(model.state_dict(), 'tut2-model.pt')
    
    print(f'Epoch: {epoch+1:02} | Epoch Time: {epoch_mins}m {epoch_secs}s')
    print(f'\tTrain Loss: {train_loss:.3f} | Train Acc: {train_acc*100:.2f}%')
    print(f'\t Val. Loss: {valid_loss:.3f} |  Val. Acc: {valid_acc*100:.2f}%')

model.load_state_dict(torch.load('tut2-model.pt'))

test_loss, test_acc = evaluate(model, test_itr, criterion)

print(f'Test Loss: {test_loss:.3f} | Test Acc: {test_acc*100:.2f}%')

import spacy
nlp = spacy.load('en_core_web_sm')

def pred(model, sentence):
    model.eval()
    tokenized = [tok.text for tok in nlp.tokenizer(sentence)]
    indexed = [txt.vocab.stoi[t] for t in tokenized]
    length = [len(indexed)]
    tensor = torch.LongTensor(indexed).to(device)
    tensor = tensor.unsqueeze(1)
    length_tensor = torch.LongTensor(length)
    prediction = torch.sigmoid(model(tensor, length_tensor))
    return prediction.item()

sent=["positive","neutral","negative"]
def print_sent(x):
  if (x<0.3): print(sent[0])
  elif (x>0.3 and x<0.7): print(sent[1])
  else: print(sent[2])

print_sent(pred(model, "Normal"))

print_sent(pred(model, "This film was average"))

print_sent(pred(model, "This film is horrible"))

print_sent(pred(model, "This film was great"))

print_sent(pred(model, "This was the best movie i have seen in a while. The cast was great and the script was awesome, and the direction just blew my mind"))

print_sent(pred(model, "the cast was dumb"))

print_sent(pred(model, "Why does this fil exist"))









