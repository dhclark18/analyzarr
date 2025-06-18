import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Container,
  Row,
  Table,
  Spinner,
  Alert,
  Button,
  Badge,
  Form,
  InputGroup
} from 'react-bootstrap';
import Layout from '../components/Layout';

export default function EpisodeDetail() {
  const { key } = useParams();
  const [episode, setEpisode] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [newTag, setNewTag] = useState('');
  const [tagOpInProgress, setTagOpInProgress] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/episode/${encodeURIComponent(key)}`)
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => setEpisode(data))
      .catch(err => setError(err.toString()))
      .finally(() => setLoading(false));
  }, [key]);

  const addTag = () => {
    if (!newTag.trim()) return;
    setTagOpInProgress(true);
    fetch(`/api/episode/${encodeURIComponent(key)}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag: newTag.trim() })
    })
      .then(res => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(() => {
        setEpisode(prev => ({
          ...prev,
          tags: [...(prev.tags || []), newTag.trim()]
        }));
        setNewTag('');
      })
      .catch(err => setError(err.toString()))
      .finally(() => setTagOpInProgress(false));
  };

  const removeTag = (tag) => {
    setTagOpInProgress(true);
    fetch(`/api/episode/${encodeURIComponent(key)}/tags/${encodeURIComponent(tag)}`, {
      method: 'DELETE'
    })
      .then(res => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(() => {
        setEpisode(prev => ({
          ...prev,
          tags: prev.tags.filter(t => t !== tag)
        }));
      })
      .catch(err => setError(err.toString()))
      .finally(() => setTagOpInProgress(false));
  };

  if (loading) {
    return (
      <Layout>
        <Container className="py-4 text-center">
          <Spinner animation="border" role="status" />
        </Container>
      </Layout>
    );
  }

  if (error) {
    return (
      <Layout>
        <Container className="py-4">
          <Alert variant="danger">Error: {error}</Alert>
          <Button as={Link} to="/" variant="outline-light" className="mt-2">
            ← Back to Library
          </Button>
        </Container>
      </Layout>
    );
  }

  return (
    <Layout>
      <Container fluid className="py-4">
        <Button as={Link} to="/" variant="outline-light" className="mb-3">
          ← Back to Library
        </Button>

        <Table striped bordered hover responsive variant="dark">
          <tbody>
            <tr>
              <th>Expected Title</th>
              <td>{episode.expectedTitle}</td>
            </tr>
            <tr>
              <th>Actual Title</th>
              <td>{episode.actualTitle}</td>
            </tr>
            <tr>
              <th>Confidence</th>
              <td>{episode.confidence}</td>
            </tr>
            <tr>
              <th>Substring Override?</th>
              <td>{episode.substring_override ? 'Yes' : 'No'}</td>
            </tr>
            <tr>
              <th>Missing Title?</th>
              <td>{episode.missing_title ? 'Yes' : 'No'}</td>
            </tr>
          </tbody>
        </Table>

        <Row className="mt-4">
          <h2>Tags</h2>
          <div>
            {(episode.tags || []).map(tag => (
              <Badge
                key={tag}
                bg="secondary"
                pill
                className="me-1"
                style={{ cursor: 'pointer' }}
                onClick={() => !tagOpInProgress && removeTag(tag)}
              >
                {tag} ×
              </Badge>
            ))}
          </div>
          <InputGroup className="mt-2" style={{ maxWidth: '300px' }}>
            <Form.Control
              placeholder="New tag"
              value={newTag}
              onChange={e => setNewTag(e.target.value)}
              disabled={tagOpInProgress}
            />
            <Button
              variant="outline-light"
              onClick={addTag}
              disabled={tagOpInProgress || !newTag.trim()}
            >
              Add
            </Button>
          </InputGroup>
        </Row>
      </Container>
    </Layout>
  );
}
